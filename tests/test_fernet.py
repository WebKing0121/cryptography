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

import base64
import calendar
import json
import os
import time

import iso8601

import pytest

import six

from cryptography.fernet import Fernet, InvalidToken


def json_parametrize(keys, fname):
    path = os.path.join(os.path.dirname(__file__), "vectors", "fernet", fname)
    with open(path) as f:
        data = json.load(f)
    return pytest.mark.parametrize(keys, [
        tuple([entry[k] for k in keys])
        for entry in data
    ])


class TestFernet(object):
    @json_parametrize(
        ("secret", "now", "iv", "src", "token"), "generate.json",
    )
    def test_generate(self, secret, now, iv, src, token):
        f = Fernet(secret.encode("ascii"))
        actual_token = f._encrypt_from_parts(
            src.encode("ascii"),
            calendar.timegm(iso8601.parse_date(now).utctimetuple()),
            b"".join(map(six.int2byte, iv))
        )
        assert actual_token == token.encode("ascii")

    @json_parametrize(
        ("secret", "now", "src", "ttl_sec", "token"), "verify.json",
    )
    def test_verify(self, secret, now, src, ttl_sec, token, monkeypatch):
        f = Fernet(secret.encode("ascii"))
        current_time = calendar.timegm(iso8601.parse_date(now).utctimetuple())
        monkeypatch.setattr(time, "time", lambda: current_time)
        payload = f.decrypt(token.encode("ascii"), ttl=ttl_sec)
        assert payload == src.encode("ascii")

    @json_parametrize(("secret", "token", "now", "ttl_sec"), "invalid.json")
    def test_invalid(self, secret, token, now, ttl_sec, monkeypatch):
        f = Fernet(secret.encode("ascii"))
        current_time = calendar.timegm(iso8601.parse_date(now).utctimetuple())
        monkeypatch.setattr(time, "time", lambda: current_time)
        with pytest.raises(InvalidToken):
            f.decrypt(token.encode("ascii"), ttl=ttl_sec)

    def test_unicode(self):
        f = Fernet(base64.urlsafe_b64encode(b"\x00" * 32))
        with pytest.raises(TypeError):
            f.encrypt(six.u(""))
        with pytest.raises(TypeError):
            f.decrypt(six.u(""))

    @pytest.mark.parametrize("message", [b"", b"Abc!", b"\x00\xFF\x00\x80"])
    def test_roundtrips(self, message):
        f = Fernet(base64.urlsafe_b64encode(b"\x00" * 32))
        assert f.decrypt(f.encrypt(message)) == message
