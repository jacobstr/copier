"""Utilities related to VCS."""
import re
import sys
import tempfile
from pathlib import Path

from packaging import version
from packaging.version import Version
from plumbum import TF, ProcessExecutionError, colors, local
from plumbum.cmd import git

from .tools import TemporaryDirectory
from .types import OptBool, OptStr, StrOrPath

GIT_PREFIX = ("git@", "git://", "git+")
GIT_POSTFIX = (".git",)
GIT_VERSION = Version(git("version").split()[-1].replace(".windows", "+windows"))
REPLACEMENTS = (
    (re.compile(r"^gh:/?(.*\.git)$"), r"https://github.com/\1"),
    (re.compile(r"^gh:/?(.*)$"), r"https://github.com/\1.git"),
    (re.compile(r"^gl:/?(.*\.git)$"), r"https://gitlab.com/\1"),
    (re.compile(r"^gl:/?(.*)$"), r"https://gitlab.com/\1.git"),
)


def is_git_repo_root(path: StrOrPath) -> bool:
    """Indicate if a given path is a git repo root directory."""
    try:
        with local.cwd(Path(path, ".git")):
            return bool(git("rev-parse", "--is-inside-git-dir").strip() == "true")
    except OSError:
        return False


def is_in_git_repo(path: StrOrPath) -> bool:
    """Indicate if a given path is in a git repo directory."""
    try:
        git("-C", path, "rev-parse", "--show-toplevel")
        return True
    except (OSError, ProcessExecutionError):
        return False


def is_git_bundle(path: Path) -> bool:
    """Indicate if a path is a valid git bundle."""
    with TemporaryDirectory(prefix=f"{__name__}.is_git_bundle.") as dirname:
        with local.cwd(dirname):
            git("init")
            return bool(git["bundle", "verify", path] & TF)


def get_repo(url: str) -> OptStr:
    """Transforms `url` into a git-parseable origin URL.

    Args:
        url:
            Valid examples:

            - gh:copier-org/copier
            - gl:copier-org/copier
            - git@github.com:copier-org/copier.git
            - git+https://mywebsiteisagitrepo.example.com/
            - /local/path/to/git/repo
            - /local/path/to/git/bundle/file.bundle
    """
    for pattern, replacement in REPLACEMENTS:
        url = re.sub(pattern, replacement, url)
    url_path = Path(url)
    if not (
        url.endswith(GIT_POSTFIX)
        or url.startswith(GIT_PREFIX)
        or is_git_repo_root(url_path)
        or is_git_bundle(url_path)
    ):
        return None

    if url.startswith("git+"):
        url = url[4:]
    return url


def checkout_latest_tag(local_repo: StrOrPath, use_prereleases: OptBool = False) -> str:
    """Checkout latest git tag and check it out, sorted by PEP 440.

    Parameters:
        local_repo:
            A git repository in the local filesystem.
        use_prereleases:
            If `False`, skip prerelease git tags.
    """
    with local.cwd(local_repo):
        all_tags = git("tag").split()
        if not use_prereleases:
            all_tags = filter(
                lambda tag: not version.parse(tag).is_prerelease, all_tags
            )
        sorted_tags = sorted(all_tags, key=version.parse, reverse=True)
        try:
            latest_tag = str(sorted_tags[0])
        except IndexError:
            print(
                colors.warn | "No git tags found in template; using HEAD as ref",
                file=sys.stderr,
            )
            latest_tag = "HEAD"
        git("checkout", "--force", latest_tag)
        git("submodule", "update", "--checkout", "--init", "--recursive", "--force")
        return latest_tag


def clone(url: str, ref: OptStr = None) -> str:
    """Clone repo into some temporary destination.

    Args:
        url:
            Git-parseable URL of the repo. As returned by
            [get_repo][copier.vcs.get_repo].
        ref:
            Reference to checkout. For Git repos, defaults to `HEAD`.
    """
    location = tempfile.mkdtemp(prefix=f"{__name__}.clone.")
    _clone = git["clone", "--no-checkout", url, location]
    # Faster clones if possible
    if GIT_VERSION >= Version("2.27"):
        _clone = _clone["--filter=blob:none"]
    _clone()
    with local.cwd(location):
        git("checkout", ref or "HEAD")
        git("submodule", "update", "--checkout", "--init", "--recursive", "--force")
    return location
