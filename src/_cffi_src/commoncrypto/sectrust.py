# This file is dual licensed under the terms of the Apache License, Version
# 2.0, and the BSD License. See the LICENSE file in the root of this repository
# for complete details.

from __future__ import absolute_import, division, print_function

INCLUDES = """
#include <Security/SecTrust.h>
"""

TYPES = """
typedef ... *SecTrustRef;
typedef uint32_t SecTrustResultType;

enum {
    kSecTrustResultInvalid,
    kSecTrustResultProceed,
    kSecTrustResultConfirm,
    kSecTrustResultDeny,
    kSecTrustResultUnspecified,
    kSecTrustResultRecoverableTrustFailure,
    kSecTrustResultFatalTrustFailure,
    kSecTrustResultOtherError
};
"""

FUNCTIONS = """
OSStatus SecTrustEvaluate(SecTrustRef, SecTrustResultType *);
OSStatus SecTrustCopyAnchorCertificates(CFArrayRef *);
"""

MACROS = """
"""

CUSTOMIZATIONS = """
"""
