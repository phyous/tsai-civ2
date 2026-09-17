# Observed native calendar labels

Original Civ II displays both number-first dates such as `4000 B.C.` and era-first dates such as `A.D. 1`. The latter was observed in attempt012 after the native year became 1. `civ2.dates` parses these labels without consulting game state or deriving a year from the turn counter.

The shared parser accepts complete ASCII BC/AD dates in either order, with optional periods and spacing. It rejects year zero, missing eras, extra eras, signs, decimal years, unreadable digits, and trailing text. City captions may continue with other native statistics after their complete date. Raw captions and founding notices remain in the observation and request evidence.

City control bindings and the offline verifier compare the parsed signed year to the independently observed native year. Review bookkeeping uses the existing `4000BC` or `1AD` token spelling, so `A.D. 1` and `1 A.D.` refer to the same displayed year. Recent founding notices and exact production-title candidates use the same equivalence; it does not establish city ownership or a native actor identity.

Pixel recovery remains separate. The status reader requires two agreeing reads of the actual row, preserves any readable digits and recognized era, and never substitutes the native year. Original attempt012 frame1533 read `A.D. J`; independent RGB and grayscale 3× crops both read `A.D. 1`. Caption recovery changes only digits corroborated by two distinct scales, retaining the original city name, era position, and remaining text.

Public tests use synthetic dates and cover both date orders, ambiguity rejection, city controls, verifier bindings, founding notices, and review identity. Optional private-image tests also cover the original BC and AD frames; they skip when those captures are unavailable.
