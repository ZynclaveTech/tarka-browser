// Tark iOS: ICU's U16_NEXT (next code point in UTF-16, advancing i).
#pragma once
#include "third_party/icu/source/common/unicode/uchar.h"
#define U16_NEXT(s, i, length, c)                                                     \
  do {                                                                                \
    (c) = (s)[(i)++];                                                                 \
    if ((c) >= 0xD800 && (c) < 0xDC00 && (size_t)(i) != (size_t)(length) &&          \
        (s)[(i)] >= 0xDC00 && (s)[(i)] < 0xE000) {                                    \
      (c) = 0x10000 + (((c) - 0xD800) << 10) + ((s)[(i)++] - 0xDC00);                 \
    }                                                                                 \
  } while (false)
