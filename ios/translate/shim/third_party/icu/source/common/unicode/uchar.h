// Tark iOS: the ICU character properties the translator uses, from iOS's own
// ICU (libicucore, which exports these names without a version suffix).
#pragma once
#include <cstdint>
using UChar32 = int32_t;
using UBool = int8_t;
enum UCharCategory { U_DECIMAL_DIGIT_NUMBER = 9, U_LETTER_NUMBER = 10, U_OTHER_NUMBER = 11, U_CURRENCY_SYMBOL = 25 };
enum UProperty { UCHAR_ALPHABETIC = 0, UCHAR_LOWERCASE = 22 };
extern "C" {
int8_t u_charType(UChar32 c);
UBool u_hasBinaryProperty(UChar32 c, UProperty which);
UBool u_isUWhiteSpace(UChar32 c);
UBool u_isalpha(UChar32 c);
UBool u_isdefined(UChar32 c);
}
#define U_MASK(x) ((uint32_t)1 << (x))
#define U_GET_GC_MASK(c) U_MASK(u_charType(c))
#define U_GC_N_MASK (U_MASK(U_DECIMAL_DIGIT_NUMBER) | U_MASK(U_LETTER_NUMBER) | U_MASK(U_OTHER_NUMBER))
