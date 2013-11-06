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

from cryptography.hazmat.primitives import interfaces


class Cipher(object):
    def __init__(self, algorithm, mode, backend=None):
        super(Cipher, self).__init__()

        if backend is None:
            from cryptography.hazmat.bindings import (
                _default_backend as backend,
            )

        self.algorithm = algorithm
        self.mode = mode
        self._backend = backend

    def encryptor(self):
        return _CipherContext(
            self._backend.ciphers.create_encrypt_ctx(self.algorithm,
                                                     self.mode))

    def decryptor(self):
        return _CipherContext(
            self._backend.ciphers.create_decrypt_ctx(self.algorithm,
                                                     self.mode))


@interfaces.register(interfaces.CipherContext)
class _CipherContext(object):
    def __init__(self, ctx):
        self._ctx = ctx

    def update(self, data):
        if self._ctx is None:
            raise ValueError("Context was already finalized")
        return self._ctx.update(data)

    def finalize(self):
        if self._ctx is None:
            raise ValueError("Context was already finalized")
        data = self._ctx.finalize()
        self._ctx = None
        return data


class AES(object):
    name = "AES"
    block_size = 128
    key_sizes = frozenset([128, 192, 256])

    def __init__(self, key):
        super(AES, self).__init__()
        self.key = key

        # Verify that the key size matches the expected key size
        if self.key_size not in self.key_sizes:
            raise ValueError("Invalid key size ({0}) for {1}".format(
                self.key_size, self.name
            ))

    @property
    def key_size(self):
        return len(self.key) * 8


class Camellia(object):
    name = "camellia"
    block_size = 128
    key_sizes = frozenset([128, 192, 256])

    def __init__(self, key):
        super(Camellia, self).__init__()
        self.key = key

        # Verify that the key size matches the expected key size
        if self.key_size not in self.key_sizes:
            raise ValueError("Invalid key size ({0}) for {1}".format(
                self.key_size, self.name
            ))

    @property
    def key_size(self):
        return len(self.key) * 8


class TripleDES(object):
    name = "3DES"
    block_size = 64
    key_sizes = frozenset([64, 128, 192])

    def __init__(self, key):
        super(TripleDES, self).__init__()
        if len(key) == 8:
            key += key + key
        elif len(key) == 16:
            key += key[:8]
        self.key = key

        # Verify that the key size matches the expected key size
        if self.key_size not in self.key_sizes:
            raise ValueError("Invalid key size ({0}) for {1}".format(
                self.key_size, self.name
            ))

    @property
    def key_size(self):
        return len(self.key) * 8


class Blowfish(object):
    name = "Blowfish"
    block_size = 64
    key_sizes = frozenset(range(32, 449, 8))

    def __init__(self, key):
        super(Blowfish, self).__init__()
        self.key = key

        # Verify that the key size matches the expected key size
        if self.key_size not in self.key_sizes:
            raise ValueError("Invalid key size ({0}) for {1}".format(
                self.key_size, self.name
            ))

    @property
    def key_size(self):
        return len(self.key) * 8


class CAST5(object):
    name = "CAST5"
    block_size = 64
    key_sizes = frozenset([40, 48, 56, 64, 72, 80, 88, 96, 104, 112, 120, 128])

    def __init__(self, key):
        super(CAST5, self).__init__()
        self.key = key

        # Verify that the key size matches the expected key size
        if self.key_size not in self.key_sizes:
            raise ValueError("Invalid key size ({0}) for {1}".format(
                self.key_size, self.name
            ))

    @property
    def key_size(self):
        return len(self.key) * 8
