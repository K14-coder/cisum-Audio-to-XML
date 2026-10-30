"""The rights notice users must accept before uploading.

Changing the wording? Bump VERSION. Every upload records the version the user
agreed to, and clients must send the current version back.
"""

RIGHTS_NOTICE_VERSION = "2026-10-30"

RIGHTS_NOTICE = {
    "version": RIGHTS_NOTICE_VERSION,
    "title": "Only upload music you have the rights to.",
    "paragraphs": [
        "By uploading, you confirm that you own or have permission for this recording and the song it contains, "
        "including the right to make a piano arrangement of it and to share that arrangement.",
        "Owning a copy of a song (for example, a purchased download) does not give you these rights.",
        "We remove arrangements reported as infringing and close the accounts of repeat infringers.",
    ],
    "checkbox_label": "I have the rights to upload this song and to share arrangements of it.",
}
