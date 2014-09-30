# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import, division, print_function

import collections
import itertools
import warnings
from contextlib import contextmanager

import six

from cryptography import utils
from cryptography.exceptions import (
    InternalError, UnsupportedAlgorithm, _Reasons
)
from cryptography.hazmat.backends.interfaces import (
    CMACBackend, CipherBackend, DSABackend, EllipticCurveBackend, HMACBackend,
    HashBackend, PBKDF2HMACBackend, PEMSerializationBackend,
    PKCS8SerializationBackend, RSABackend,
    TraditionalOpenSSLSerializationBackend
)
from cryptography.hazmat.backends.openssl.ciphers import (
    _AESCTRCipherContext, _CipherContext
)
from cryptography.hazmat.backends.openssl.cmac import _CMACContext
from cryptography.hazmat.backends.openssl.dsa import (
    _DSAParameters, _DSAPrivateKey, _DSAPublicKey,
    _DSASignatureContext, _DSAVerificationContext
)
from cryptography.hazmat.backends.openssl.ec import (
    _EllipticCurvePrivateKey, _EllipticCurvePublicKey
)
from cryptography.hazmat.backends.openssl.hashes import _HashContext
from cryptography.hazmat.backends.openssl.hmac import _HMACContext
from cryptography.hazmat.backends.openssl.rsa import (
    _RSAPrivateKey, _RSAPublicKey
)
from cryptography.hazmat.bindings.openssl.binding import Binding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, ec, rsa
from cryptography.hazmat.primitives.asymmetric.padding import (
    MGF1, OAEP, PKCS1v15, PSS
)
from cryptography.hazmat.primitives.ciphers.algorithms import (
    AES, ARC4, Blowfish, CAST5, Camellia, IDEA, SEED, TripleDES
)
from cryptography.hazmat.primitives.ciphers.modes import (
    CBC, CFB, CFB8, CTR, ECB, GCM, OFB
)


_MemoryBIO = collections.namedtuple("_MemoryBIO", ["bio", "char_ptr"])
_OpenSSLError = collections.namedtuple("_OpenSSLError",
                                       ["code", "lib", "func", "reason"])


@utils.register_interface(CipherBackend)
@utils.register_interface(CMACBackend)
@utils.register_interface(DSABackend)
@utils.register_interface(EllipticCurveBackend)
@utils.register_interface(HashBackend)
@utils.register_interface(HMACBackend)
@utils.register_interface(PBKDF2HMACBackend)
@utils.register_interface(PKCS8SerializationBackend)
@utils.register_interface(RSABackend)
@utils.register_interface(TraditionalOpenSSLSerializationBackend)
@utils.register_interface(PEMSerializationBackend)
class Backend(object):
    """
    OpenSSL API binding interfaces.
    """
    name = "openssl"

    def __init__(self):
        self._binding = Binding()
        self._ffi = self._binding.ffi
        self._lib = self._binding.lib

        self._binding.init_static_locks()

        # adds all ciphers/digests for EVP
        self._lib.OpenSSL_add_all_algorithms()
        # registers available SSL/TLS ciphers and digests
        self._lib.SSL_library_init()
        # loads error strings for libcrypto and libssl functions
        self._lib.SSL_load_error_strings()

        self._cipher_registry = {}
        self._register_default_ciphers()
        self.activate_osrandom_engine()

    def activate_builtin_random(self):
        # Obtain a new structural reference.
        e = self._lib.ENGINE_get_default_RAND()
        if e != self._ffi.NULL:
            self._lib.ENGINE_unregister_RAND(e)
            # Reset the RNG to use the new engine.
            self._lib.RAND_cleanup()
            # decrement the structural reference from get_default_RAND
            res = self._lib.ENGINE_finish(e)
            assert res == 1

    def activate_osrandom_engine(self):
        # Unregister and free the current engine.
        self.activate_builtin_random()
        # Fetches an engine by id and returns it. This creates a structural
        # reference.
        e = self._lib.ENGINE_by_id(self._lib.Cryptography_osrandom_engine_id)
        assert e != self._ffi.NULL
        # Initialize the engine for use. This adds a functional reference.
        res = self._lib.ENGINE_init(e)
        assert res == 1
        # Set the engine as the default RAND provider.
        res = self._lib.ENGINE_set_default_RAND(e)
        assert res == 1
        # Decrement the structural ref incremented by ENGINE_by_id.
        res = self._lib.ENGINE_free(e)
        assert res == 1
        # Decrement the functional ref incremented by ENGINE_init.
        res = self._lib.ENGINE_finish(e)
        assert res == 1
        # Reset the RNG to use the new engine.
        self._lib.RAND_cleanup()

    def openssl_version_text(self):
        """
        Friendly string name of the loaded OpenSSL library. This is not
        necessarily the same version as it was compiled against.

        Example: OpenSSL 1.0.1e 11 Feb 2013
        """
        return self._ffi.string(
            self._lib.SSLeay_version(self._lib.SSLEAY_VERSION)
        ).decode("ascii")

    def create_hmac_ctx(self, key, algorithm):
        return _HMACContext(self, key, algorithm)

    def hash_supported(self, algorithm):
        digest = self._lib.EVP_get_digestbyname(algorithm.name.encode("ascii"))
        return digest != self._ffi.NULL

    def hmac_supported(self, algorithm):
        return self.hash_supported(algorithm)

    def create_hash_ctx(self, algorithm):
        return _HashContext(self, algorithm)

    def cipher_supported(self, cipher, mode):
        if self._evp_cipher_supported(cipher, mode):
            return True
        elif isinstance(mode, CTR) and isinstance(cipher, AES):
            return True
        else:
            return False

    def _evp_cipher_supported(self, cipher, mode):
        try:
            adapter = self._cipher_registry[type(cipher), type(mode)]
        except KeyError:
            return False
        evp_cipher = adapter(self, cipher, mode)
        return self._ffi.NULL != evp_cipher

    def register_cipher_adapter(self, cipher_cls, mode_cls, adapter):
        if (cipher_cls, mode_cls) in self._cipher_registry:
            raise ValueError("Duplicate registration for: {0} {1}.".format(
                cipher_cls, mode_cls)
            )
        self._cipher_registry[cipher_cls, mode_cls] = adapter

    def _register_default_ciphers(self):
        for mode_cls in [CBC, CTR, ECB, OFB, CFB, CFB8]:
            self.register_cipher_adapter(
                AES,
                mode_cls,
                GetCipherByName("{cipher.name}-{cipher.key_size}-{mode.name}")
            )
        for mode_cls in [CBC, CTR, ECB, OFB, CFB]:
            self.register_cipher_adapter(
                Camellia,
                mode_cls,
                GetCipherByName("{cipher.name}-{cipher.key_size}-{mode.name}")
            )
        for mode_cls in [CBC, CFB, CFB8, OFB]:
            self.register_cipher_adapter(
                TripleDES,
                mode_cls,
                GetCipherByName("des-ede3-{mode.name}")
            )
        self.register_cipher_adapter(
            TripleDES,
            ECB,
            GetCipherByName("des-ede3")
        )
        for mode_cls in [CBC, CFB, OFB, ECB]:
            self.register_cipher_adapter(
                Blowfish,
                mode_cls,
                GetCipherByName("bf-{mode.name}")
            )
        for mode_cls in [CBC, CFB, OFB, ECB]:
            self.register_cipher_adapter(
                SEED,
                mode_cls,
                GetCipherByName("seed-{mode.name}")
            )
        for cipher_cls, mode_cls in itertools.product(
            [CAST5, IDEA],
            [CBC, OFB, CFB, ECB],
        ):
            self.register_cipher_adapter(
                cipher_cls,
                mode_cls,
                GetCipherByName("{cipher.name}-{mode.name}")
            )
        self.register_cipher_adapter(
            ARC4,
            type(None),
            GetCipherByName("rc4")
        )
        self.register_cipher_adapter(
            AES,
            GCM,
            GetCipherByName("{cipher.name}-{cipher.key_size}-{mode.name}")
        )

    def create_symmetric_encryption_ctx(self, cipher, mode):
        if (isinstance(mode, CTR) and isinstance(cipher, AES)
                and not self._evp_cipher_supported(cipher, mode)):
            # This is needed to provide support for AES CTR mode in OpenSSL
            # 0.9.8. It can be removed when we drop 0.9.8 support (RHEL 5
            # extended life ends 2020).
            return _AESCTRCipherContext(self, cipher, mode)
        else:
            return _CipherContext(self, cipher, mode, _CipherContext._ENCRYPT)

    def create_symmetric_decryption_ctx(self, cipher, mode):
        if (isinstance(mode, CTR) and isinstance(cipher, AES)
                and not self._evp_cipher_supported(cipher, mode)):
            # This is needed to provide support for AES CTR mode in OpenSSL
            # 0.9.8. It can be removed when we drop 0.9.8 support (RHEL 5
            # extended life ends 2020).
            return _AESCTRCipherContext(self, cipher, mode)
        else:
            return _CipherContext(self, cipher, mode, _CipherContext._DECRYPT)

    def pbkdf2_hmac_supported(self, algorithm):
        if self._lib.Cryptography_HAS_PBKDF2_HMAC:
            return self.hmac_supported(algorithm)
        else:
            # OpenSSL < 1.0.0 has an explicit PBKDF2-HMAC-SHA1 function,
            # so if the PBKDF2_HMAC function is missing we only support
            # SHA1 via PBKDF2_HMAC_SHA1.
            return isinstance(algorithm, hashes.SHA1)

    def derive_pbkdf2_hmac(self, algorithm, length, salt, iterations,
                           key_material):
        buf = self._ffi.new("char[]", length)
        if self._lib.Cryptography_HAS_PBKDF2_HMAC:
            evp_md = self._lib.EVP_get_digestbyname(
                algorithm.name.encode("ascii"))
            assert evp_md != self._ffi.NULL
            res = self._lib.PKCS5_PBKDF2_HMAC(
                key_material,
                len(key_material),
                salt,
                len(salt),
                iterations,
                evp_md,
                length,
                buf
            )
            assert res == 1
        else:
            if not isinstance(algorithm, hashes.SHA1):
                raise UnsupportedAlgorithm(
                    "This version of OpenSSL only supports PBKDF2HMAC with "
                    "SHA1.",
                    _Reasons.UNSUPPORTED_HASH
                )
            res = self._lib.PKCS5_PBKDF2_HMAC_SHA1(
                key_material,
                len(key_material),
                salt,
                len(salt),
                iterations,
                length,
                buf
            )
            assert res == 1

        return self._ffi.buffer(buf)[:]

    def _err_string(self, code):
        err_buf = self._ffi.new("char[]", 256)
        self._lib.ERR_error_string_n(code, err_buf, 256)
        return self._ffi.string(err_buf, 256)[:]

    def _consume_errors(self):
        errors = []
        while True:
            code = self._lib.ERR_get_error()
            if code == 0:
                break

            lib = self._lib.ERR_GET_LIB(code)
            func = self._lib.ERR_GET_FUNC(code)
            reason = self._lib.ERR_GET_REASON(code)

            errors.append(_OpenSSLError(code, lib, func, reason))
        return errors

    def _unknown_error(self, error):
        return InternalError(
            "Unknown error code {0} from OpenSSL, "
            "you should probably file a bug. {1}.".format(
                error.code, self._err_string(error.code)
            )
        )

    def _bn_to_int(self, bn):
        if six.PY3:
            # Python 3 has constant time from_bytes, so use that.

            bn_num_bytes = (self._lib.BN_num_bits(bn) + 7) // 8
            bin_ptr = self._ffi.new("unsigned char[]", bn_num_bytes)
            bin_len = self._lib.BN_bn2bin(bn, bin_ptr)
            assert bin_len > 0
            assert bin_ptr != self._ffi.NULL
            return int.from_bytes(self._ffi.buffer(bin_ptr)[:bin_len], "big")

        else:
            # Under Python 2 the best we can do is hex()

            hex_cdata = self._lib.BN_bn2hex(bn)
            assert hex_cdata != self._ffi.NULL
            hex_str = self._ffi.string(hex_cdata)
            self._lib.OPENSSL_free(hex_cdata)
            return int(hex_str, 16)

    def _int_to_bn(self, num, bn=None):
        """
        Converts a python integer to a BIGNUM. The returned BIGNUM will not
        be garbage collected (to support adding them to structs that take
        ownership of the object). Be sure to register it for GC if it will
        be discarded after use.
        """

        if bn is None:
            bn = self._ffi.NULL

        if six.PY3:
            # Python 3 has constant time to_bytes, so use that.

            binary = num.to_bytes(int(num.bit_length() / 8.0 + 1), "big")
            bn_ptr = self._lib.BN_bin2bn(binary, len(binary), bn)
            assert bn_ptr != self._ffi.NULL
            return bn_ptr

        else:
            # Under Python 2 the best we can do is hex()

            hex_num = hex(num).rstrip("L").lstrip("0x").encode("ascii") or b"0"
            bn_ptr = self._ffi.new("BIGNUM **")
            bn_ptr[0] = bn
            res = self._lib.BN_hex2bn(bn_ptr, hex_num)
            assert res != 0
            assert bn_ptr[0] != self._ffi.NULL
            return bn_ptr[0]

    def generate_rsa_private_key(self, public_exponent, key_size):
        rsa._verify_rsa_parameters(public_exponent, key_size)

        rsa_cdata = self._lib.RSA_new()
        assert rsa_cdata != self._ffi.NULL
        rsa_cdata = self._ffi.gc(rsa_cdata, self._lib.RSA_free)

        bn = self._int_to_bn(public_exponent)
        bn = self._ffi.gc(bn, self._lib.BN_free)

        res = self._lib.RSA_generate_key_ex(
            rsa_cdata, key_size, bn, self._ffi.NULL
        )
        assert res == 1

        return _RSAPrivateKey(self, rsa_cdata)

    def generate_rsa_parameters_supported(self, public_exponent, key_size):
        return (public_exponent >= 3 and public_exponent & 1 != 0 and
                key_size >= 512)

    def load_rsa_private_numbers(self, numbers):
        rsa._check_private_key_components(
            numbers.p,
            numbers.q,
            numbers.d,
            numbers.dmp1,
            numbers.dmq1,
            numbers.iqmp,
            numbers.public_numbers.e,
            numbers.public_numbers.n
        )
        rsa_cdata = self._lib.RSA_new()
        assert rsa_cdata != self._ffi.NULL
        rsa_cdata = self._ffi.gc(rsa_cdata, self._lib.RSA_free)
        rsa_cdata.p = self._int_to_bn(numbers.p)
        rsa_cdata.q = self._int_to_bn(numbers.q)
        rsa_cdata.d = self._int_to_bn(numbers.d)
        rsa_cdata.dmp1 = self._int_to_bn(numbers.dmp1)
        rsa_cdata.dmq1 = self._int_to_bn(numbers.dmq1)
        rsa_cdata.iqmp = self._int_to_bn(numbers.iqmp)
        rsa_cdata.e = self._int_to_bn(numbers.public_numbers.e)
        rsa_cdata.n = self._int_to_bn(numbers.public_numbers.n)
        res = self._lib.RSA_blinding_on(rsa_cdata, self._ffi.NULL)
        assert res == 1

        return _RSAPrivateKey(self, rsa_cdata)

    def load_rsa_public_numbers(self, numbers):
        rsa._check_public_key_components(numbers.e, numbers.n)
        rsa_cdata = self._lib.RSA_new()
        assert rsa_cdata != self._ffi.NULL
        rsa_cdata = self._ffi.gc(rsa_cdata, self._lib.RSA_free)
        rsa_cdata.e = self._int_to_bn(numbers.e)
        rsa_cdata.n = self._int_to_bn(numbers.n)
        res = self._lib.RSA_blinding_on(rsa_cdata, self._ffi.NULL)
        assert res == 1

        return _RSAPublicKey(self, rsa_cdata)

    def _bytes_to_bio(self, data):
        """
        Return a _MemoryBIO namedtuple of (BIO, char*).

        The char* is the storage for the BIO and it must stay alive until the
        BIO is finished with.
        """
        data_char_p = self._ffi.new("char[]", data)
        bio = self._lib.BIO_new_mem_buf(
            data_char_p, len(data)
        )
        assert bio != self._ffi.NULL

        return _MemoryBIO(self._ffi.gc(bio, self._lib.BIO_free), data_char_p)

    def _evp_pkey_to_private_key(self, evp_pkey):
        """
        Return the appropriate type of PrivateKey given an evp_pkey cdata
        pointer.
        """

        type = evp_pkey.type

        if type == self._lib.EVP_PKEY_RSA:
            rsa_cdata = self._lib.EVP_PKEY_get1_RSA(evp_pkey)
            assert rsa_cdata != self._ffi.NULL
            rsa_cdata = self._ffi.gc(rsa_cdata, self._lib.RSA_free)
            return _RSAPrivateKey(self, rsa_cdata)
        elif type == self._lib.EVP_PKEY_DSA:
            dsa_cdata = self._lib.EVP_PKEY_get1_DSA(evp_pkey)
            assert dsa_cdata != self._ffi.NULL
            dsa_cdata = self._ffi.gc(dsa_cdata, self._lib.DSA_free)
            return _DSAPrivateKey(self, dsa_cdata)
        elif (self._lib.Cryptography_HAS_EC == 1 and
              type == self._lib.EVP_PKEY_EC):
            ec_cdata = self._lib.EVP_PKEY_get1_EC_KEY(evp_pkey)
            assert ec_cdata != self._ffi.NULL
            ec_cdata = self._ffi.gc(ec_cdata, self._lib.EC_KEY_free)
            return _EllipticCurvePrivateKey(self, ec_cdata)
        else:
            raise UnsupportedAlgorithm("Unsupported key type.")

    def _evp_pkey_to_public_key(self, evp_pkey):
        """
        Return the appropriate type of PublicKey given an evp_pkey cdata
        pointer.
        """

        type = evp_pkey.type

        if type == self._lib.EVP_PKEY_RSA:
            rsa_cdata = self._lib.EVP_PKEY_get1_RSA(evp_pkey)
            assert rsa_cdata != self._ffi.NULL
            rsa_cdata = self._ffi.gc(rsa_cdata, self._lib.RSA_free)
            return _RSAPublicKey(self, rsa_cdata)
        elif type == self._lib.EVP_PKEY_DSA:
            dsa_cdata = self._lib.EVP_PKEY_get1_DSA(evp_pkey)
            assert dsa_cdata != self._ffi.NULL
            dsa_cdata = self._ffi.gc(dsa_cdata, self._lib.DSA_free)
            return _DSAPublicKey(self, dsa_cdata)
        elif (self._lib.Cryptography_HAS_EC == 1 and
              type == self._lib.EVP_PKEY_EC):
            ec_cdata = self._lib.EVP_PKEY_get1_EC_KEY(evp_pkey)
            assert ec_cdata != self._ffi.NULL
            ec_cdata = self._ffi.gc(ec_cdata, self._lib.EC_KEY_free)
            return _EllipticCurvePublicKey(self, ec_cdata)
        else:
            raise UnsupportedAlgorithm("Unsupported key type.")

    def _pem_password_cb(self, password):
        """
        Generate a pem_password_cb function pointer that copied the password to
        OpenSSL as required and returns the number of bytes copied.

        typedef int pem_password_cb(char *buf, int size,
                                    int rwflag, void *userdata);

        Useful for decrypting PKCS8 files and so on.

        Returns a tuple of (cdata function pointer, callback function).
        """

        def pem_password_cb(buf, size, writing, userdata):
            pem_password_cb.called += 1

            if not password:
                pem_password_cb.exception = TypeError(
                    "Password was not given but private key is encrypted."
                )
                return 0
            elif len(password) < size:
                pw_buf = self._ffi.buffer(buf, size)
                pw_buf[:len(password)] = password
                return len(password)
            else:
                pem_password_cb.exception = ValueError(
                    "Passwords longer than {0} bytes are not supported "
                    "by this backend.".format(size - 1)
                )
                return 0

        pem_password_cb.called = 0
        pem_password_cb.exception = None

        return (
            self._ffi.callback("int (char *, int, int, void *)",
                               pem_password_cb),
            pem_password_cb
        )

    def _mgf1_hash_supported(self, algorithm):
        if self._lib.Cryptography_HAS_MGF1_MD:
            return self.hash_supported(algorithm)
        else:
            return isinstance(algorithm, hashes.SHA1)

    def rsa_padding_supported(self, padding):
        if isinstance(padding, PKCS1v15):
            return True
        elif isinstance(padding, PSS) and isinstance(padding._mgf, MGF1):
            return self._mgf1_hash_supported(padding._mgf._algorithm)
        elif isinstance(padding, OAEP) and isinstance(padding._mgf, MGF1):
            return isinstance(padding._mgf._algorithm, hashes.SHA1)
        else:
            return False

    def generate_dsa_parameters(self, key_size):
        if key_size not in (1024, 2048, 3072):
            raise ValueError(
                "Key size must be 1024 or 2048 or 3072 bits.")

        if (self._lib.OPENSSL_VERSION_NUMBER < 0x1000000f and
                key_size > 1024):
            raise ValueError(
                "Key size must be 1024 because OpenSSL < 1.0.0 doesn't "
                "support larger key sizes.")

        ctx = self._lib.DSA_new()
        assert ctx != self._ffi.NULL
        ctx = self._ffi.gc(ctx, self._lib.DSA_free)

        res = self._lib.DSA_generate_parameters_ex(
            ctx, key_size, self._ffi.NULL, 0,
            self._ffi.NULL, self._ffi.NULL, self._ffi.NULL
        )

        assert res == 1

        return _DSAParameters(self, ctx)

    def generate_dsa_private_key(self, parameters):
        ctx = self._lib.DSA_new()
        assert ctx != self._ffi.NULL
        ctx = self._ffi.gc(ctx, self._lib.DSA_free)
        if isinstance(parameters, dsa.DSAParameters):
            ctx.p = self._int_to_bn(parameters.p)
            ctx.q = self._int_to_bn(parameters.q)
            ctx.g = self._int_to_bn(parameters.g)
        else:
            ctx.p = self._lib.BN_dup(parameters._dsa_cdata.p)
            ctx.q = self._lib.BN_dup(parameters._dsa_cdata.q)
            ctx.g = self._lib.BN_dup(parameters._dsa_cdata.g)

        self._lib.DSA_generate_key(ctx)

        return _DSAPrivateKey(self, ctx)

    def generate_dsa_private_key_and_parameters(self, key_size):
        parameters = self.generate_dsa_parameters(key_size)
        return self.generate_dsa_private_key(parameters)

    def create_dsa_signature_ctx(self, private_key, algorithm):
        warnings.warn(
            "create_dsa_signature_ctx is deprecated and will be removed in "
            "a future version.",
            utils.DeprecatedIn05,
            stacklevel=2
        )
        dsa_cdata = self._dsa_cdata_from_private_key(private_key)
        key = _DSAPrivateKey(self, dsa_cdata)
        return _DSASignatureContext(self, key, algorithm)

    def create_dsa_verification_ctx(self, public_key, signature,
                                    algorithm):
        warnings.warn(
            "create_dsa_verification_ctx is deprecated and will be removed in "
            "a future version.",
            utils.DeprecatedIn05,
            stacklevel=2
        )
        dsa_cdata = self._dsa_cdata_from_public_key(public_key)
        key = _DSAPublicKey(self, dsa_cdata)
        return _DSAVerificationContext(self, key, signature, algorithm)

    def load_dsa_private_numbers(self, numbers):
        dsa._check_dsa_private_numbers(numbers)
        parameter_numbers = numbers.public_numbers.parameter_numbers

        dsa_cdata = self._lib.DSA_new()
        assert dsa_cdata != self._ffi.NULL
        dsa_cdata = self._ffi.gc(dsa_cdata, self._lib.DSA_free)

        dsa_cdata.p = self._int_to_bn(parameter_numbers.p)
        dsa_cdata.q = self._int_to_bn(parameter_numbers.q)
        dsa_cdata.g = self._int_to_bn(parameter_numbers.g)
        dsa_cdata.pub_key = self._int_to_bn(numbers.public_numbers.y)
        dsa_cdata.priv_key = self._int_to_bn(numbers.x)

        return _DSAPrivateKey(self, dsa_cdata)

    def load_dsa_public_numbers(self, numbers):
        dsa._check_dsa_parameters(numbers.parameter_numbers)
        dsa_cdata = self._lib.DSA_new()
        assert dsa_cdata != self._ffi.NULL
        dsa_cdata = self._ffi.gc(dsa_cdata, self._lib.DSA_free)

        dsa_cdata.p = self._int_to_bn(numbers.parameter_numbers.p)
        dsa_cdata.q = self._int_to_bn(numbers.parameter_numbers.q)
        dsa_cdata.g = self._int_to_bn(numbers.parameter_numbers.g)
        dsa_cdata.pub_key = self._int_to_bn(numbers.y)

        return _DSAPublicKey(self, dsa_cdata)

    def load_dsa_parameter_numbers(self, numbers):
        dsa._check_dsa_parameters(numbers)
        dsa_cdata = self._lib.DSA_new()
        assert dsa_cdata != self._ffi.NULL
        dsa_cdata = self._ffi.gc(dsa_cdata, self._lib.DSA_free)

        dsa_cdata.p = self._int_to_bn(numbers.p)
        dsa_cdata.q = self._int_to_bn(numbers.q)
        dsa_cdata.g = self._int_to_bn(numbers.g)

        return _DSAParameters(self, dsa_cdata)

    def _dsa_cdata_from_public_key(self, public_key):
        ctx = self._lib.DSA_new()
        assert ctx != self._ffi.NULL
        ctx = self._ffi.gc(ctx, self._lib.DSA_free)
        parameters = public_key.parameters()
        ctx.p = self._int_to_bn(parameters.p)
        ctx.q = self._int_to_bn(parameters.q)
        ctx.g = self._int_to_bn(parameters.g)
        ctx.pub_key = self._int_to_bn(public_key.y)
        return ctx

    def _dsa_cdata_from_private_key(self, private_key):
        ctx = self._lib.DSA_new()
        assert ctx != self._ffi.NULL
        ctx = self._ffi.gc(ctx, self._lib.DSA_free)
        parameters = private_key.parameters()
        ctx.p = self._int_to_bn(parameters.p)
        ctx.q = self._int_to_bn(parameters.q)
        ctx.g = self._int_to_bn(parameters.g)
        ctx.priv_key = self._int_to_bn(private_key.x)
        ctx.pub_key = self._int_to_bn(private_key.y)
        return ctx

    def dsa_hash_supported(self, algorithm):
        if self._lib.OPENSSL_VERSION_NUMBER < 0x1000000f:
            return isinstance(algorithm, hashes.SHA1)
        else:
            return self.hash_supported(algorithm)

    def dsa_parameters_supported(self, p, q, g):
        if self._lib.OPENSSL_VERSION_NUMBER < 0x1000000f:
            return (utils.bit_length(p) <= 1024 and utils.bit_length(q) <= 160)
        else:
            return True

    def cmac_algorithm_supported(self, algorithm):
        return (
            self._lib.Cryptography_HAS_CMAC == 1
            and self.cipher_supported(algorithm, CBC(
                b"\x00" * algorithm.block_size))
        )

    def create_cmac_ctx(self, algorithm):
        return _CMACContext(self, algorithm)

    def load_pem_private_key(self, data, password):
        return self._load_key(
            self._lib.PEM_read_bio_PrivateKey,
            self._evp_pkey_to_private_key,
            data,
            password,
        )

    def load_pem_public_key(self, data):
        return self._load_key(
            self._lib.PEM_read_bio_PUBKEY,
            self._evp_pkey_to_public_key,
            data,
            None,
        )

    def load_traditional_openssl_pem_private_key(self, data, password):
        warnings.warn(
            "load_traditional_openssl_pem_private_key is deprecated and will "
            "be removed in a future version, use load_pem_private_key "
            "instead.",
            utils.DeprecatedIn06,
            stacklevel=2
        )
        return self.load_pem_private_key(data, password)

    def load_pkcs8_pem_private_key(self, data, password):
        warnings.warn(
            "load_pkcs8_pem_private_key is deprecated and will be removed in a"
            " future version, use load_pem_private_key instead.",
            utils.DeprecatedIn06,
            stacklevel=2
        )
        return self.load_pem_private_key(data, password)

    def _load_key(self, openssl_read_func, convert_func, data, password):
        mem_bio = self._bytes_to_bio(data)

        password_callback, password_func = self._pem_password_cb(password)

        evp_pkey = openssl_read_func(
            mem_bio.bio,
            self._ffi.NULL,
            password_callback,
            self._ffi.NULL
        )

        if evp_pkey == self._ffi.NULL:
            if password_func.exception is not None:
                errors = self._consume_errors()
                assert errors
                raise password_func.exception
            else:
                self._handle_key_loading_error()

        evp_pkey = self._ffi.gc(evp_pkey, self._lib.EVP_PKEY_free)

        if password is not None and password_func.called == 0:
            raise TypeError(
                "Password was given but private key is not encrypted.")

        assert (
            (password is not None and password_func.called == 1) or
            password is None
        )

        return convert_func(evp_pkey)

    def _handle_key_loading_error(self):
        errors = self._consume_errors()

        if not errors:
            raise ValueError("Could not unserialize key data.")

        elif errors[0][1:] == (
            self._lib.ERR_LIB_EVP,
            self._lib.EVP_F_EVP_DECRYPTFINAL_EX,
            self._lib.EVP_R_BAD_DECRYPT
        ):
            raise ValueError("Bad decrypt. Incorrect password?")

        elif errors[0][1:] in (
            (
                self._lib.ERR_LIB_PEM,
                self._lib.PEM_F_PEM_GET_EVP_CIPHER_INFO,
                self._lib.PEM_R_UNSUPPORTED_ENCRYPTION
            ),

            (
                self._lib.ERR_LIB_EVP,
                self._lib.EVP_F_EVP_PBE_CIPHERINIT,
                self._lib.EVP_R_UNKNOWN_PBE_ALGORITHM
            )
        ):
            raise UnsupportedAlgorithm(
                "PEM data is encrypted with an unsupported cipher",
                _Reasons.UNSUPPORTED_CIPHER
            )

        elif any(
            error[1:] == (
                self._lib.ERR_LIB_EVP,
                self._lib.EVP_F_EVP_PKCS82PKEY,
                self._lib.EVP_R_UNSUPPORTED_PRIVATE_KEY_ALGORITHM
            )
            for error in errors
        ):
            raise UnsupportedAlgorithm(
                "Unsupported public key algorithm.",
                _Reasons.UNSUPPORTED_PUBLIC_KEY_ALGORITHM
            )

        else:
            assert errors[0][1] in (
                self._lib.ERR_LIB_EVP,
                self._lib.ERR_LIB_PEM,
                self._lib.ERR_LIB_ASN1,
            )
            raise ValueError("Could not unserialize key data.")

    def elliptic_curve_supported(self, curve):
        if self._lib.Cryptography_HAS_EC != 1:
            return False

        try:
            curve_nid = self._elliptic_curve_to_nid(curve)
        except UnsupportedAlgorithm:
            curve_nid = self._lib.NID_undef

        ctx = self._lib.EC_GROUP_new_by_curve_name(curve_nid)

        if ctx == self._ffi.NULL:
            errors = self._consume_errors()
            assert (
                curve_nid == self._lib.NID_undef or
                errors[0][1:] == (
                    self._lib.ERR_LIB_EC,
                    self._lib.EC_F_EC_GROUP_NEW_BY_CURVE_NAME,
                    self._lib.EC_R_UNKNOWN_GROUP
                )
            )
            return False
        else:
            assert curve_nid != self._lib.NID_undef
            self._lib.EC_GROUP_free(ctx)
            return True

    def elliptic_curve_signature_algorithm_supported(
        self, signature_algorithm, curve
    ):
        if self._lib.Cryptography_HAS_EC != 1:
            return False

        # We only support ECDSA right now.
        if not isinstance(signature_algorithm, ec.ECDSA):
            return False

        # Before 0.9.8m OpenSSL can't cope with digests longer than the curve.
        if (
            self._lib.OPENSSL_VERSION_NUMBER < 0x009080df and
            curve.key_size < signature_algorithm.algorithm.digest_size * 8
        ):
            return False

        return self.elliptic_curve_supported(curve)

    def generate_elliptic_curve_private_key(self, curve):
        """
        Generate a new private key on the named curve.
        """

        if self.elliptic_curve_supported(curve):
            curve_nid = self._elliptic_curve_to_nid(curve)

            ec_cdata = self._lib.EC_KEY_new_by_curve_name(curve_nid)
            assert ec_cdata != self._ffi.NULL
            ec_cdata = self._ffi.gc(ec_cdata, self._lib.EC_KEY_free)

            res = self._lib.EC_KEY_generate_key(ec_cdata)
            assert res == 1

            res = self._lib.EC_KEY_check_key(ec_cdata)
            assert res == 1

            return _EllipticCurvePrivateKey(self, ec_cdata)
        else:
            raise UnsupportedAlgorithm(
                "Backend object does not support {0}.".format(curve.name),
                _Reasons.UNSUPPORTED_ELLIPTIC_CURVE
            )

    def elliptic_curve_private_key_from_numbers(self, numbers):
        warnings.warn(
            "elliptic_curve_private_key_from_numbers is deprecated and will "
            "be removed in a future version.",
            utils.DeprecatedIn06,
            stacklevel=2
        )
        return self.load_elliptic_curve_private_numbers(numbers)

    def load_elliptic_curve_private_numbers(self, numbers):
        public = numbers.public_numbers

        curve_nid = self._elliptic_curve_to_nid(public.curve)

        ec_cdata = self._lib.EC_KEY_new_by_curve_name(curve_nid)
        assert ec_cdata != self._ffi.NULL
        ec_cdata = self._ffi.gc(ec_cdata, self._lib.EC_KEY_free)

        ec_cdata = self._ec_key_set_public_key_affine_coordinates(
            ec_cdata, public.x, public.y)

        res = self._lib.EC_KEY_set_private_key(
            ec_cdata, self._int_to_bn(numbers.private_value))
        assert res == 1

        return _EllipticCurvePrivateKey(self, ec_cdata)

    def elliptic_curve_public_key_from_numbers(self, numbers):
        warnings.warn(
            "elliptic_curve_public_key_from_numbers is deprecated and will be "
            "removed in a future version.",
            utils.DeprecatedIn06,
            stacklevel=2
        )
        return self.load_elliptic_curve_public_numbers(numbers)

    def load_elliptic_curve_public_numbers(self, numbers):
        curve_nid = self._elliptic_curve_to_nid(numbers.curve)

        ec_cdata = self._lib.EC_KEY_new_by_curve_name(curve_nid)
        assert ec_cdata != self._ffi.NULL
        ec_cdata = self._ffi.gc(ec_cdata, self._lib.EC_KEY_free)

        ec_cdata = self._ec_key_set_public_key_affine_coordinates(
            ec_cdata, numbers.x, numbers.y)

        return _EllipticCurvePublicKey(self, ec_cdata)

    def _elliptic_curve_to_nid(self, curve):
        """
        Get the NID for a curve name.
        """

        curve_aliases = {
            "secp192r1": "prime192v1",
            "secp256r1": "prime256v1"
        }

        curve_name = curve_aliases.get(curve.name, curve.name)

        curve_nid = self._lib.OBJ_sn2nid(curve_name.encode())
        if curve_nid == self._lib.NID_undef:
            raise UnsupportedAlgorithm(
                "{0} is not a supported elliptic curve".format(curve.name),
                _Reasons.UNSUPPORTED_ELLIPTIC_CURVE
            )
        return curve_nid

    @contextmanager
    def _tmp_bn_ctx(self):
        bn_ctx = self._lib.BN_CTX_new()
        assert bn_ctx != self._ffi.NULL
        bn_ctx = self._ffi.gc(bn_ctx, self._lib.BN_CTX_free)
        self._lib.BN_CTX_start(bn_ctx)
        try:
            yield bn_ctx
        finally:
            self._lib.BN_CTX_end(bn_ctx)

    def _ec_key_determine_group_get_set_funcs(self, ctx):
        """
        Given an EC_KEY determine the group and what methods are required to
        get/set point coordinates.
        """
        assert ctx != self._ffi.NULL

        nid_two_field = self._lib.OBJ_sn2nid(b"characteristic-two-field")
        assert nid_two_field != self._lib.NID_undef

        group = self._lib.EC_KEY_get0_group(ctx)
        assert group != self._ffi.NULL

        method = self._lib.EC_GROUP_method_of(group)
        assert method != self._ffi.NULL

        nid = self._lib.EC_METHOD_get_field_type(method)
        assert nid != self._lib.NID_undef

        if nid == nid_two_field and self._lib.Cryptography_HAS_EC2M:
            set_func = self._lib.EC_POINT_set_affine_coordinates_GF2m
            get_func = self._lib.EC_POINT_get_affine_coordinates_GF2m
        else:
            set_func = self._lib.EC_POINT_set_affine_coordinates_GFp
            get_func = self._lib.EC_POINT_get_affine_coordinates_GFp

        assert set_func and get_func

        return set_func, get_func, group

    def _ec_key_set_public_key_affine_coordinates(self, ctx, x, y):
        """
        This is a port of EC_KEY_set_public_key_affine_coordinates that was
        added in 1.0.1.

        Sets the public key point in the EC_KEY context to the affine x and y
        values.
        """

        bn_x = self._int_to_bn(x)
        bn_y = self._int_to_bn(y)

        set_func, get_func, group = (
            self._ec_key_determine_group_get_set_funcs(ctx)
        )

        point = self._lib.EC_POINT_new(group)
        assert point != self._ffi.NULL
        point = self._ffi.gc(point, self._lib.EC_POINT_free)

        with self._tmp_bn_ctx() as bn_ctx:
            check_x = self._lib.BN_CTX_get(bn_ctx)
            check_y = self._lib.BN_CTX_get(bn_ctx)

            res = set_func(group, point, bn_x, bn_y, bn_ctx)
            assert res == 1

            res = get_func(group, point, check_x, check_y, bn_ctx)
            assert res == 1

            assert (
                self._lib.BN_cmp(bn_x, check_x) == 0 and
                self._lib.BN_cmp(bn_y, check_y) == 0
            )

        res = self._lib.EC_KEY_set_public_key(ctx, point)
        assert res == 1

        res = self._lib.EC_KEY_check_key(ctx)
        assert res == 1

        return ctx


class GetCipherByName(object):
    def __init__(self, fmt):
        self._fmt = fmt

    def __call__(self, backend, cipher, mode):
        cipher_name = self._fmt.format(cipher=cipher, mode=mode).lower()
        return backend._lib.EVP_get_cipherbyname(cipher_name.encode("ascii"))


backend = Backend()
