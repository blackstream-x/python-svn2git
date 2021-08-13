# python-svn2git

_python-svn2git_ is a translation of the great
[svn2git](https://github.com/nirvdrum/svn2git) utility to Python 3,
plus scripts to determine all commit auhors from the subversion repository,
and to push the converted git repository to a hosted repository.

## Requirements

* **Python 3.6** or newer
* git
* git-svn (the command `git svn` must be available).
* svn

## svn2git.py: Migrate a Subversion repository to Git

The **svn2git.py** script can be used as a drop-in replacement
for the original **svn2git** command, just requiring Python instead of Ruby.

The original documentation applies here too,
except for the `--password` option that has been removed
because it is not supported by git-svn.

The usage message produced by `svn2git.py --help` is:

```
usage: svn2git.py [-h] [-v] [--username NAME] [--authors AUTHORS_FILE]
                  [--exclude REGEX [REGEX ...]] [-m] [--no-minimize-url]
                  [--revision START_REV[:END_REV]]
                  [--branches BRANCHES_PATH [BRANCHES_PATH ...] |
                  --nobranches] [--tags TAGS_PATH [TAGS_PATH ...] | --notags]
                  [--trunk TRUNK_PATH | --notrunk] [--rootistrunk] [--rebase]
                  [--rebasebranch REBASEBRANCH]
                  [SVN_URL]

Migrate projects from Subversion to Git

positional arguments:
  SVN_URL               Subversion repository URL

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         Output all messages including debug level
  --username NAME       Username for transports that need it (http(s), svn)
  --authors AUTHORS_FILE
                        Path to file containing svn-to-git authors mapping
                        (default: ~/.svn2git/authors)
  --exclude REGEX [REGEX ...]
                        Specify a Perl regular expression to filter paths to
                        exclude from fetching; can be used multiple times
  -m, --metadata        Include metadata in git logs (git-svn-id)
  --no-minimize-url     Accept URLs as-is without attempting to connect to a
                        higher level directory
  --revision START_REV[:END_REV]
                        Start importing from SVN revision START_REV;
                        optionally end at END_REV
  --branches BRANCHES_PATH [BRANCHES_PATH ...]
                        Subpath to branches from repository URL (default:
                        branches); can be used multiple times
  --nobranches          Do not try to import any branches
  --tags TAGS_PATH [TAGS_PATH ...]
                        Subpath to tags from repository URL (default: tags);
                        can be used multiple times
  --notags              Do not try to import any tags
  --trunk TRUNK_PATH    Subpath to trunk from repository URL (default: trunk)
  --notrunk             Do not import anything from trunk
  --rootistrunk         Use this if the root level of the repo is equivalent
                        to the trunk and there are no tags or branches. In
                        that case, any other options regarding trunk, tags or
                        branches will be ignored.
  --rebase              Instead of cloning a new project, rebase an existing
                        one against SVN
  --rebasebranch REBASEBRANCH
                        Rebase the specified branch
```

## push_all.py: Push a local Git repository to a hosted one

The **push_all.py** script can be used to push a local git repository to
a hosted (empty) remote repository as described in
<https://docs.gitlab.com/ee/user/project/import/svn.html#cut-over-migration-with-svn2git>
(basically wrapping the commands in the last code block there).

If the origin URL that was configured using either `git remote add origin`
or the option `--set-origin` is an HTTP URL (i.e. starts with `http:` or `https:`),
the script checks if the Git option `credential.helper` has been set,
and exits if it is not set. Otherwise, you would end up entering your
credentials over and over again, especially when using the
`--batch-size` option.

If you get a message reading

`fatal: pack exceeds maximum allowed size`

when running this script, then there are pack size limits configured
on the remote side.

In that case, you should try the `--batch-size` option
with a value of 500 or 1000.
This will enable incremental pushes of (maximum) this number of commits,
and reduce the batch size dynamically if required, thus dramatically improving
the chance to get your local repository pushed completely.

The usage message produced by `push_all.py --help` is:

```
usage: push_all.py [-h] [-v] [--set-origin GIT_URL] [--batch-size BATCH_SIZE]
                   [--fail-fast] [--ignore-missing-credential-helper]

Push the contents of a local Git repository to its origin URL

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         Output all messages including debug level
  --set-origin GIT_URL  URL to push to (if omitted, the existing URL for
                        origin will be used).
  --batch-size BATCH_SIZE
                        Maximum batch size (the number of commits that will be
                        pushed). Required if the upstream repository rejects a
                        global push with the message "fatal: pack exceeds
                        maximum allowed size". In that case use a value of
                        500. After each unsuccessful attempt, the batch size
                        will be halved for the current branch (and doubled
                        again after a successful push, up to the given
                        maximum). If this option is omitted or set to zero, a
                        global push will be attempted.
  --fail-fast           Exit directly after the first branch failed to be
                        pushed.
  --ignore-missing-credential-helper
                        Ignore (the lack of) the credential.helper git option.
```

## unique_commit_authors.py: Determine Subversion repository authors

The **unique_commit_authors.py** script examines the log of either
a subversion repository’s working copy located in the current directory,
or that of the subversion repository at the specified URL,
and produces a list of unique commit authors on stdout.

This script requires a Subversion command line client (i.e. **svn**)
to be installed.

You can redirect standard output to a file
and use that file as a starting point to create the authors file for the
`--authors` option of **svn2git**.


The usage message produced by `unique_commit_authors.py --help` is:

```
rainer@esplendor [~] $ python-svn2git/unique_commit_authors.py -h
usage: unique_commit_authors.py [-h] [-q] [-v] [-c CHUNK_SIZE] [-s]
                                [--svn-command SVN_COMMAND]
                                [SVN_URL]

Print unique authors from the subversion log.

positional arguments:
  SVN_URL               Subversion repository URL. If omitted, inspect the log
                        of the working copy in the current directory instead.

optional arguments:
  -h, --help            show this help message and exit
  -q, --quiet           Output error and warning messages only.
  -v, --verbose         Output all messages.
  -c CHUNK_SIZE, --chunk-size CHUNK_SIZE
                        Split the Subversion log into chunks of CHUNK_SIZE
                        revisions (default: 5000).
  -s, --per-user-statistics
                        Print per-user statistics.
  --svn-command SVN_COMMAND
                        Subversion command line client executable path.
                        Normally, the default value (svn) is sufficient, but
                        there might exist cases where the executable is stored
                        in a non-standard location not included in the system
                        path (e.g. /opt/CollabNet_Subversion/bin/svn).
```

## Putting it all together

**Generalized workflow:**
1. Determine unique authors from the Subversion repository
   using **unique_commit_authors.py**, redirecting its standard output
   to a text file.
2. Modify the text file – either by hand or by an appropriate utility
   for your environment – to contain a mapping of each author entry to a
   real name and email in the form
   ```svnauthor = git author name <email address>```
3. Use **svn2git.py** with the authors text file to create a
   local Git repository with the correct authors.
4. Use **push_all.py** with a remote URL to push your newly created
   local Git repository to a hosted repository.

See [example.md](./example.md) for a small example.

## Found a bug or got a feature request?

Feel free to open an issue [here](https://github.com/blackstream-x/python-svn2git/issues).
