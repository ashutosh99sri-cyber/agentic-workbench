# Licensing and public release

Owner decision, 17 October 2026: the owner confirmed distribution rights for the
original code, documentation, examples and WOOKhoop branding, and approved a
public current-source preview under the existing Apache-2.0 terms with retained
third-party notices. This records the owner's attestation; it is not independent
legal verification or permission to omit component licenses. Future contributions,
bundled environments and registry releases still require their applicable checks.

Agentic Workbench currently declares **Apache-2.0** for its original project
contributions in [the Python metadata](../../pyproject.toml) and
[the Node adapter metadata](../../adapters/node/package.json). The full terms are
in [LICENSE](../../LICENSE) and the adapter's [LICENSE](../../adapters/node/LICENSE).
The recommended release choice is to retain Apache-2.0 and preserve each
third-party component's own terms.

WOOKhoop branding does not establish copyright ownership, contributor authority,
or permission to relicense another person's work. Before public release, the
owner must confirm the right to distribute the original code, documentation,
examples, and instructions under the stated license, including any applicable
employment, customer, or prior-project restrictions. Confirm the correct legal
copyright identity before adding an ownership statement. Git author metadata
alone does not establish those rights.

## License choice

The following is a practical comparison of the primary license texts. The
actual terms govern each use and distribution.

| Choice | Distribution approach | Patent terms | Implication for this project |
| --- | --- | --- | --- |
| [MIT](https://opensource.org/license/mit) | Permissive; retain the copyright and permission notice with copies or substantial portions. | No express patent grant in the license text. | A possible owner-authorized choice for original work, but changing to it would not remove third-party notice obligations. |
| [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0) | Permissive; provide the license, retain applicable notices, identify modified files as required, and preserve relevant upstream NOTICE content. | Express contributor patent grant and patent-litigation termination terms. | Matches the existing project declarations and preserves their explicit patent terms. |
| [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html) | Copyleft; conveying covered modified or combined works can require GPL licensing and corresponding source under its terms. | Express contributor patent provisions, with additional conditions. | Would be a deliberate owner-authorized product decision with downstream distribution consequences; this review established no requirement to switch the project to GPL. |

Any future license change requires confirming authority over every affected
contribution and reviewing compatibility with included third-party material.
It cannot remove existing upstream obligations or revoke rights already granted
for previously distributed versions.

## Included third-party material

[NOTICE](../../NOTICE) records the adapted Ponytail engineering guidance and
the small more-itertools source snippet in the historical corpus's negative
control. [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) contains the full
MIT permission notices, including the upstream copyright statements. Preserve
these notices with the applicable distributed material. The design references
in [source provenance](../design/SOURCE-PROVENANCE.md) do not by themselves
establish ownership or provide permission for copied content.

The historical repair corpus's checks are recorded as independently authored.
Its pinned external archives retain the upstream more-itertools MIT, Click
BSD-3-Clause, and packaging Apache-2.0/BSD-2-Clause license files. The repository
does not bundle those complete archives. Anyone redistributing an archive,
prepared upstream source tree, or further copied material must preserve its
applicable license and notices. See the [corpus record](../../evaluations/python/README.md).

## Dependencies and redistribution

Dependencies installed separately from the Python and Node package registries
retain their own licenses. The lockfiles identify versions and artifacts; they
are not a substitute for those artifacts' license files. Publishing this source
repository or a package that declares dependencies differs from redistributing
an environment, image, or executable bundle that contains the dependencies.

The locked runtime dependency `pathspec==1.1.1` uses
[MPL-2.0](https://www.mozilla.org/en-US/MPL/2.0/). MPL covers its files and any
covered modifications. Source distributions of those files must retain MPL
terms and notices; executable distributions must also make the covered source
available and tell recipients how to obtain it under the license. MPL permits
a larger work under other terms when its requirements for the covered software
are met. This separately installed dependency therefore does not by itself
change Agentic Workbench's original code to MPL or GPL.

The local review did not have installed artifacts for three conditional locked
dependencies: `colorama==0.4.6`, `httpx2-jsfetch==1.0`, and `tomli==2.5.0`. Review
the exact artifacts' license files before redistributing a bundle that contains
them. Do not present this review as clearance of every dependency on every
supported platform. Development dependencies also keep their licenses; for
example, a bundled development environment containing `coverage==7.16.2` must
retain its applicable Apache license and NOTICE material.

## Owner release confirmations

Before approving public release, the owner must confirm distribution rights,
the intended public Git history and author metadata, permission to use WOOKhoop
branding, and the exact repository/package destinations. The owner must also
name consenting maintainers and establish and test a real private security
reporting channel under [SECURITY.md](../../SECURITY.md), plus a conduct intake
procedure that establishes a private channel before collecting incident details under [CODE_OF_CONDUCT.md](../../CODE_OF_CONDUCT.md).

These documents preserve attribution and record release decisions and remaining
checks. They do not certify legal ownership or replace explicit publication
approval. Follow the [release process](../releasing.md) and
[maintainer setup](../../MAINTAINERS.md) before publication.
