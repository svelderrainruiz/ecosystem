"""NI docker image pull planner (INST-REQ-099, 100): by the pinned digest, only after both licence boxes, on the user's machine.
The image is never shipped or mirrored: this module only asks the local engine to pull; it has no push, save or export."""
import re

from installer import licences, schema as schema_mod
from installer.schema import ImageNotPinned

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
REPOSITORY = re.compile(r"[a-z0-9][a-z0-9._/-]*")


def reference(repository, digest):
    if not DIGEST.fullmatch(digest or ""):
        raise ImageNotPinned("the image is pulled only by a pinned sha256 digest, never by a tag")
    if not REPOSITORY.fullmatch(repository or ""):
        raise ImageNotPinned("the image repository name is not valid")
    return "%s@%s" % (repository, digest)


def pull_image(schema, variant, year, ticks, repository, engine):
    licences.require_both(ticks)
    ref = reference(repository, schema_mod.pinned_digest(schema, variant, year))
    engine.pull(["pull", "--", ref])
    return ref
