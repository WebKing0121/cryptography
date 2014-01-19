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
#include <openssl/dh.h>
"""

TYPES = """
typedef struct dh_st {
    BIGNUM *p;              // prime number (shared)
    BIGNUM *g;              // generator of Z_p (shared)
    BIGNUM *priv_key;       // private DH value x
    BIGNUM *pub_key;        // public DH value g^x
    ...;
} DH;
"""

FUNCTIONS = """
DH *DH_new(void);
void DH_free(DH *);
"""

MACROS = """
"""

CUSTOMIZATIONS = """
"""

CONDITIONAL_NAMES = {}
