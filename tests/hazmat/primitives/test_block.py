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

import binascii

import pytest

from cryptography import utils
from cryptography.exceptions import UnsupportedAlgorithm, AlreadyFinalized
from cryptography.hazmat.primitives import interfaces
from cryptography.hazmat.primitives.ciphers import (
    Cipher, algorithms, modes
)


@utils.register_interface(interfaces.CipherAlgorithm)
class DummyCipher(object):
    pass


class DummyMode(object):
    def validate_for_algorithm(self, algorithm):
        pass


class TestCipher(object):
    def test_instantiate_without_backend(self):
        Cipher(
            algorithms.AES(binascii.unhexlify(b"0" * 32)),
            modes.CBC(binascii.unhexlify(b"0" * 32))
        )

    def test_creates_encryptor(self):
        cipher = Cipher(
            algorithms.AES(binascii.unhexlify(b"0" * 32)),
            modes.CBC(binascii.unhexlify(b"0" * 32))
        )
        assert isinstance(cipher.encryptor(), interfaces.CipherContext)

    def test_creates_decryptor(self):
        cipher = Cipher(
            algorithms.AES(binascii.unhexlify(b"0" * 32)),
            modes.CBC(binascii.unhexlify(b"0" * 32))
        )
        assert isinstance(cipher.decryptor(), interfaces.CipherContext)

    def test_instantiate_with_non_algorithm(self):
        algorithm = object()
        with pytest.raises(TypeError):
            Cipher(algorithm, mode=None)


class TestCipherContext(object):
    def test_use_after_finalize(self, backend):
        cipher = Cipher(
            algorithms.AES(binascii.unhexlify(b"0" * 32)),
            modes.CBC(binascii.unhexlify(b"0" * 32)),
            backend
        )
        encryptor = cipher.encryptor()
        encryptor.update(b"a" * 16)
        encryptor.finalize()
        with pytest.raises(AlreadyFinalized):
            encryptor.update(b"b" * 16)
        with pytest.raises(AlreadyFinalized):
            encryptor.finalize()
        decryptor = cipher.decryptor()
        decryptor.update(b"a" * 16)
        decryptor.finalize()
        with pytest.raises(AlreadyFinalized):
            decryptor.update(b"b" * 16)
        with pytest.raises(AlreadyFinalized):
            decryptor.finalize()

    def test_unaligned_block_encryption(self, backend):
        cipher = Cipher(
            algorithms.AES(binascii.unhexlify(b"0" * 32)),
            modes.ECB(),
            backend
        )
        encryptor = cipher.encryptor()
        ct = encryptor.update(b"a" * 15)
        assert ct == b""
        ct += encryptor.update(b"a" * 65)
        assert len(ct) == 80
        ct += encryptor.finalize()
        decryptor = cipher.decryptor()
        pt = decryptor.update(ct[:3])
        assert pt == b""
        pt += decryptor.update(ct[3:])
        assert len(pt) == 80
        assert pt == b"a" * 80
        decryptor.finalize()

    def test_nonexistent_cipher(self, backend):
        cipher = Cipher(
            DummyCipher(), DummyMode(), backend
        )
        with pytest.raises(UnsupportedAlgorithm):
            cipher.encryptor()

        with pytest.raises(UnsupportedAlgorithm):
            cipher.decryptor()


class TestModeValidation(object):
    def test_cbc(self, backend):
        with pytest.raises(ValueError):
            Cipher(
                algorithms.AES(b"\x00" * 16),
                modes.CBC(b"abc"),
                backend,
            )

    def test_ofb(self, backend):
        with pytest.raises(ValueError):
            Cipher(
                algorithms.AES(b"\x00" * 16),
                modes.OFB(b"abc"),
                backend,
            )

    def test_cfb(self, backend):
        with pytest.raises(ValueError):
            Cipher(
                algorithms.AES(b"\x00" * 16),
                modes.CFB(b"abc"),
                backend,
            )

    def test_ctr(self, backend):
        with pytest.raises(ValueError):
            Cipher(
                algorithms.AES(b"\x00" * 16),
                modes.CFB(b"abc"),
                backend,
            )
