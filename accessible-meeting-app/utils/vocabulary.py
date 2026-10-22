"""Common meeting words (roughly most-used first). Used to auto-correct fingerspelling and to suggest words."""

_WORDS = """
i you we they he she it me my your our their this that these those here there what when where why how who which
is am are was were be been do does did can could will would should may might must have has had not no yes please
thank thanks sorry hello hi hey bye goodbye welcome good great fine nice well ok okay sure right wrong maybe
the a an and or but so if because then also very too more less much many some any all none every each other
to of in on at by for with from about into over under after before again now today tomorrow yesterday later soon
morning afternoon evening night week month year time minute hour second day monday tuesday wednesday thursday
friday saturday sunday
meeting agenda topic question answer idea plan project team work task deadline report update review decision
budget price cost money pay paid invoice client customer manager host member group company office home school
class student teacher problem issue solution support help need want like love know think understand believe
agree disagree repeat slow slowly fast louder quiet clear hear see look watch read write say tell ask explain
speak talk listen wait stop start begin end finish continue next last first second third open close join leave
come go going come came went get got give gave take took make made put bring send share show use find call
camera screen sound audio video microphone mute unmute chat message email phone number link file document
slide page presentation demo test result data list item step part point example number
people person man woman boy girl friend family mother father brother sister child children name age
food water coffee tea lunch dinner breakfast eat drink break rest sleep
happy sad angry tired busy free ready late early new old big small long short high low hot cold easy hard
important urgent possible impossible different same together alone best better worse
can't cannot don't won't didn't doesn't isn't aren't wasn't i'm i've i'll you're that's what's let's
hello everyone everybody someone anyone nobody nothing something anything everything
again always never often sometimes already still just only even really actually
above below between inside outside near far left right up down back front
one two three four five six seven eight nine ten eleven twelve twenty thirty hundred thousand
online offline internet network connection signal problem working broken fix fixed
accessible accessibility sign language deaf blind
""".split()

# de-duplicate, keep order
COMMON_WORDS = list(dict.fromkeys(w.lower() for w in _WORDS))
VOCAB_SET = set(COMMON_WORDS)
