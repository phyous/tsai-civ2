# Original city locator

An existing model choice names the owned city to inspect. The controller opens
the original Find City list, clicks that exact unique row, observes the list
again, and clicks its separately verified Zoom To City button. Neither the
current default row nor a foreign city substitutes for the requested target.

The original list can include visible foreign entries such as `Paris (French)`.
For the calibrated 640×480 frame, `city_locator.py` checks the original FINDCITY
resource hash, the complete outer and list borders, all three buttons, the
single-column row geometry, and the empty list area below the final row. Foreign
suffixes must be actual civilization adjectives from the original rules.
Every observed row remains in classifier evidence; only exact owned names become
navigation targets. This is visible UI context, not a foreign-state observer.

The private regression is attempt 011 frame 3101: eleven visible rows, including
eight owned cities and three foreign-labelled cities. Its retained PNG hash is
`61bb9fbaaa079f4077ad535c7be94cde8d729c187f7caf0b745b6fa07f1a9724`.
Other window layouts fail closed. The old owned-only path is unchanged.
