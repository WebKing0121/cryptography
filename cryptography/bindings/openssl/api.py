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

import itertools
import sys

import cffi

from cryptography.primitives import interfaces
from cryptography.primitives.block.ciphers import AES, Camellia
from cryptography.primitives.block.modes import CBC, ECB, OFB, CFB


class GetCipherByName(object):
    def __init__(self, fmt):
        self._fmt = fmt

    def __call__(self, api, cipher, mode):
        cipher_name = self._fmt.format(cipher=cipher, mode=mode).lower()
        return api.lib.EVP_get_cipherbyname(cipher_name)


class API(object):
    """
    OpenSSL API wrapper.
    """
    _modules = [
        "bignum",
        "bio",
        "conf",
        "crypto",
        "dh",
        "dsa",
        "engine",
        "err",
        "evp",
        "opensslv",
        "rand",
        "rsa",
        "ssl",
    ]

    def __init__(self):
        self.ffi = cffi.FFI()
        includes = []
        functions = []
        macros = []
        for name in self._modules:
            __import__("cryptography.bindings.openssl." + name)
            module = sys.modules["cryptography.bindings.openssl." + name]
            self.ffi.cdef(module.TYPES)

            macros.append(module.MACROS)
            functions.append(module.FUNCTIONS)
            includes.append(module.INCLUDES)

        # loop over the functions & macros after declaring all the types
        # so we can set interdependent types in different files and still
        # have them all defined before we parse the funcs & macros
        for func in functions:
            self.ffi.cdef(func)
        for macro in macros:
            self.ffi.cdef(macro)

        # We include functions here so that if we got any of their definitions
        # wrong, the underlying C compiler will explode. In C you are allowed
        # to re-declare a function if it has the same signature. That is:
        #   int foo(int);
        #   int foo(int);
        # is legal, but the following will fail to compile:
        #   int foo(int);
        #   int foo(short);
        self.lib = self.ffi.verify(
            source="\n".join(includes + functions),
            libraries=["crypto", "ssl"],
        )

        self.lib.OpenSSL_add_all_algorithms()
        self.lib.SSL_load_error_strings()

        self._cipher_registry = {}
        self._register_default_ciphers()

    def openssl_version_text(self):
        """
        Friendly string name of linked OpenSSL.

        Example: OpenSSL 1.0.1e 11 Feb 2013
        """
        return self.ffi.string(self.lib.OPENSSL_VERSION_TEXT).decode("ascii")

    def supports_cipher(self, cipher, mode):
        try:
            adapter = self._cipher_registry[type(cipher), type(mode)]
        except KeyError:
            return False
        evp_cipher = adapter(self, cipher, mode)
        return self.ffi.NULL != evp_cipher

    def register_cipher_adapter(self, cipher_cls, mode_cls, adapter):
        if (cipher_cls, mode_cls) in self._cipher_registry:
            raise ValueError("Duplicate registration for: {0} {1}".format(
                cipher_cls, mode_cls)
            )
        self._cipher_registry[cipher_cls, mode_cls] = adapter

    def _register_default_ciphers(self):
        for cipher_cls, mode_cls in itertools.product(
            [AES, Camellia],
            [CBC, ECB, OFB, CFB],
        ):
            self.register_cipher_adapter(
                cipher_cls,
                mode_cls,
                GetCipherByName("{cipher.name}-{cipher.key_size}-{mode.name}")
            )

    def create_block_cipher_context(self, cipher, mode):
        ctx = self.ffi.new("EVP_CIPHER_CTX *")
        res = self.lib.EVP_CIPHER_CTX_init(ctx)
        assert res != 0
        ctx = self.ffi.gc(ctx, self.lib.EVP_CIPHER_CTX_cleanup)
        evp_cipher = self._cipher_registry[type(cipher), type(mode)](
            self, cipher, mode
        )

        assert evp_cipher != self.ffi.NULL
        if isinstance(mode, interfaces.ModeWithInitializationVector):
            iv_nonce = mode.initialization_vector
        else:
            iv_nonce = self.ffi.NULL

        # TODO: Sometimes this needs to be a DecryptInit, when?
        res = self.lib.EVP_EncryptInit_ex(
            ctx, evp_cipher, self.ffi.NULL, cipher.key, iv_nonce
        )
        assert res != 0

        # We purposely disable padding here as it's handled higher up in the
        # API.
        self.lib.EVP_CIPHER_CTX_set_padding(ctx, 0)
        return ctx

    def update_encrypt_context(self, ctx, plaintext):
        buf = self.ffi.new("unsigned char[]", len(plaintext))
        outlen = self.ffi.new("int *")
        res = self.lib.EVP_EncryptUpdate(
            ctx, buf, outlen, plaintext, len(plaintext)
        )
        assert res != 0
        return self.ffi.buffer(buf)[:outlen[0]]

    def finalize_encrypt_context(self, ctx):
        cipher = self.lib.EVP_CIPHER_CTX_cipher(ctx)
        block_size = self.lib.EVP_CIPHER_block_size(cipher)
        buf = self.ffi.new("unsigned char[]", block_size)
        outlen = self.ffi.new("int *")
        res = self.lib.EVP_EncryptFinal_ex(ctx, buf, outlen)
        assert res != 0
        res = self.lib.EVP_CIPHER_CTX_cleanup(ctx)
        assert res != 0
        return self.ffi.buffer(buf)[:outlen[0]]


api = API()
