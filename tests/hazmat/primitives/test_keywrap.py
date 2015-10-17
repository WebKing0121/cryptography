# This file is dual licensed under the terms of the Apache License, Version
# 2.0, and the BSD License. See the LICENSE file in the root of this repository
# for complete details.

from __future__ import absolute_import, division, print_function

import binascii
import os

import pytest

from cryptography.hazmat.backends.interfaces import CipherBackend
from cryptography.hazmat.primitives import keywrap
from cryptography.hazmat.primitives.ciphers import algorithms, modes

from .utils import _load_all_params
from ...utils import load_nist_vectors


@pytest.mark.requires_backend_interface(interface=CipherBackend)
class TestAESKeyWrap(object):
    @pytest.mark.parametrize(
        "params",
        _load_all_params(
            os.path.join("keywrap", "kwtestvectors"),
            ["KW_AE_128.txt", "KW_AE_192.txt", "KW_AE_256.txt"],
            load_nist_vectors
        )
    )
    @pytest.mark.supported(
        only_if=lambda backend: backend.cipher_supported(
            algorithms.AES("\x00" * 16), modes.ECB()
        ),
        skip_message="Does not support AES key wrap (RFC 3394) because AES-ECB"
                     " is unsupported",
    )
    def test_wrap(self, backend, params):
        wrapping_key = binascii.unhexlify(params["k"])
        key_to_wrap = binascii.unhexlify(params["p"])
        wrapped_key = keywrap.aes_key_wrap(wrapping_key, key_to_wrap, backend)
        assert params["c"] == binascii.hexlify(wrapped_key)

    @pytest.mark.parametrize(
        "params",
        _load_all_params(
            os.path.join("keywrap", "kwtestvectors"),
            ["KW_AD_128.txt", "KW_AD_192.txt", "KW_AD_256.txt"],
            load_nist_vectors
        )
    )
    @pytest.mark.supported(
        only_if=lambda backend: backend.cipher_supported(
            algorithms.AES("\x00" * 16), modes.ECB()
        ),
        skip_message="Does not support AES key wrap (RFC 3394) because AES-ECB"
                     " is unsupported",
    )
    def test_unwrap(self, backend, params):
        wrapping_key = binascii.unhexlify(params["k"])
        wrapped_key = binascii.unhexlify(params["c"])
        if params.get("fail") is True:
            with pytest.raises(keywrap.InvalidUnwrap):
                keywrap.aes_key_unwrap(wrapping_key, wrapped_key, backend)
        else:
            unwrapped_key = keywrap.aes_key_unwrap(
                wrapping_key, wrapped_key, backend
            )
            assert params["p"] == binascii.hexlify(unwrapped_key)

    @pytest.mark.supported(
        only_if=lambda backend: backend.cipher_supported(
            algorithms.AES("\x00" * 16), modes.ECB()
        ),
        skip_message="Does not support AES key wrap (RFC 3394) because AES-ECB"
                     " is unsupported",
    )
    def test_wrap_invalid_key_length(self, backend):
        with pytest.raises(ValueError):
            keywrap.aes_key_wrap(b"badkey", b"sixteen_byte_key", backend)

    @pytest.mark.supported(
        only_if=lambda backend: backend.cipher_supported(
            algorithms.AES("\x00" * 16), modes.ECB()
        ),
        skip_message="Does not support AES key wrap (RFC 3394) because AES-ECB"
                     " is unsupported",
    )
    def test_unwrap_invalid_key_length(self, backend):
        with pytest.raises(ValueError):
            keywrap.aes_key_unwrap(b"badkey", b"\x00" * 24, backend)

    @pytest.mark.supported(
        only_if=lambda backend: backend.cipher_supported(
            algorithms.AES("\x00" * 16), modes.ECB()
        ),
        skip_message="Does not support AES key wrap (RFC 3394) because AES-ECB"
                     " is unsupported",
    )
    def test_wrap_invalid_key_to_wrap_length(self, backend):
        with pytest.raises(ValueError):
            keywrap.aes_key_wrap(b"sixteen_byte_key", b"\x00" * 15, backend)

        with pytest.raises(ValueError):
            keywrap.aes_key_wrap(b"sixteen_byte_key", b"\x00" * 23, backend)

    def test_unwrap_invalid_wrapped_key_length(self, backend):
        with pytest.raises(ValueError):
            keywrap.aes_key_unwrap(b"sixteen_byte_key", b"\x00" * 16, backend)

        with pytest.raises(ValueError):
            keywrap.aes_key_unwrap(b"sixteen_byte_key", b"\x00" * 27, backend)
