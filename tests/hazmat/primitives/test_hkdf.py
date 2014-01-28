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

import pytest

from cryptography import exceptions
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


@pytest.mark.hash
class TestHKDF(object):
    def test_length_limit(self, backend):
        big_length = 255 * (hashes.SHA256().digest_size // 8) + 1

        with pytest.raises(ValueError):
            HKDF(
                hashes.SHA256(),
                big_length,
                salt=None,
                info=None,
                backend=backend
            )

    def test_already_finalized(self, backend):
        hkdf = HKDF(
            hashes.SHA256(),
            16,
            salt=None,
            info=None,
            backend=backend
        )

        hkdf.derive('\x01' * 16)

        with pytest.raises(exceptions.AlreadyFinalized):
            hkdf.derive('\x02' * 16)

        hkdf = HKDF(
            hashes.SHA256(),
            16,
            salt=None,
            info=None,
            backend=backend
        )

        hkdf.verify('\x01' * 16, 'gJ\xfb{\xb1Oi\xc5sMC\xb7\xe4@\xf7u')

        with pytest.raises(exceptions.AlreadyFinalized):
            hkdf.verify('\x02' * 16, 'gJ\xfb{\xb1Oi\xc5sMC\xb7\xe4@\xf7u')

    def test_verify(self, backend):
        hkdf = HKDF(
            hashes.SHA256(),
            16,
            salt=None,
            info=None,
            backend=backend
        )

        hkdf.verify('\x01' * 16, 'gJ\xfb{\xb1Oi\xc5sMC\xb7\xe4@\xf7u')

    def test_verify_invalid(self, backend):
        hkdf = HKDF(
            hashes.SHA256(),
            16,
            salt=None,
            info=None,
            backend=backend
        )

        with pytest.raises(exceptions.InvalidKey):
            hkdf.verify('\x02' * 16, 'gJ\xfb{\xb1Oi\xc5sMC\xb7\xe4@\xf7u')
