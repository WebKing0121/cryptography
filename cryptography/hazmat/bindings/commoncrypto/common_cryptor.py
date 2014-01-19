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

INCLUDES = """
#include <CommonCrypto/CommonCryptor.h>
"""

TYPES = """
enum {
    kCCAlgorithmAES128 = 0,
    kCCAlgorithmDES,
    kCCAlgorithm3DES,
    kCCAlgorithmCAST,
    kCCAlgorithmRC4,
    kCCAlgorithmRC2,
    kCCAlgorithmBlowfish
};
typedef uint32_t CCAlgorithm;
enum {
    kCCSuccess = 0,
    kCCParamError = -4300,
    kCCBufferTooSmall = -4301,
    kCCMemoryFailure = -4302,
    kCCAlignmentError = -4303,
    kCCDecodeError = -4304,
    kCCUnimplemented = -4305
};
typedef int32_t CCCryptorStatus;
typedef uint32_t CCOptions;
enum {
    kCCEncrypt = 0,
    kCCDecrypt,
};
typedef uint32_t CCOperation;
typedef ... *CCCryptorRef;

enum {
    kCCModeOptionCTR_LE = 0x0001,
    kCCModeOptionCTR_BE = 0x0002
};

typedef uint32_t CCModeOptions;

enum {
    kCCModeECB = 1,
    kCCModeCBC = 2,
    kCCModeCFB = 3,
    kCCModeCTR = 4,
    kCCModeF8 = 5,
    kCCModeLRW = 6,
    kCCModeOFB = 7,
    kCCModeXTS = 8,
    kCCModeRC4 = 9,
    kCCModeCFB8 = 10,
};
typedef uint32_t CCMode;
enum {
    ccNoPadding = 0,
    ccPKCS7Padding = 1,
};
typedef uint32_t CCPadding;
"""

FUNCTIONS = """
CCCryptorStatus CCCryptorCreateWithMode(CCOperation, CCMode, CCAlgorithm,
                                        CCPadding, const void *, const void *,
                                        size_t, const void *, size_t, int,
                                        CCModeOptions, CCCryptorRef *);

CCCryptorStatus CCCryptorCreate(CCOperation, CCAlgorithm, CCOptions,
                                const void *, size_t, const void *,
                                CCCryptorRef *);
CCCryptorStatus CCCryptorUpdate(CCCryptorRef, const void *, size_t, void *,
                                size_t, size_t *);
CCCryptorStatus CCCryptorFinal(CCCryptorRef, void *, size_t, size_t *);
CCCryptorStatus CCCryptorRelease(CCCryptorRef);
"""

MACROS = """
"""

CUSTOMIZATIONS = """
"""

CONDITIONAL_NAMES = {}
