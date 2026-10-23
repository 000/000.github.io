# Borrow to Learn — mobile app information and policies

This directory publishes the English/Thai information pages for **Borrow to Learn (B2L)**, iOS and Android identifier `com.tanatt.borrowtolearn`. The bundled teaching examples use invented measures and are intended for ages 13 and above. Optional Microsoft report features, where available in the installed version, have separate data, permissions and provider processing.

The repository's existing GitHub Pages custom domain is **defense.engineer**. Use the direct HTTPS URLs below in store fields. The `000.github.io` address currently redirects to the custom domain; it is not the preferred direct policy URL. `index.html` explicitly provides the directory landing page, so publication does not depend on README rendering.

| Document | Purpose | File | Direct HTTPS URL |
| --- | --- | --- | --- |
| Information hub | Public directory index | `index.html` | [Open](https://defense.engineer/policy/) |
| Privacy policy | Privacy-policy link for both stores and inside the app | `privacy-policy.html` | [Open](https://defense.engineer/policy/privacy-policy.html) |
| App support | App Store Connect Support URL; Google Play contact/help | `support.html` | [Open](https://defense.engineer/policy/support.html) |
| About the app | App Store Connect Marketing URL | `marketing.html` | [Open](https://defense.engineer/policy/marketing.html) |
| Data deletion | Local-data and privacy-request instructions; no B2L accounts in version1.0 | `data-deletion.html` | [Open](https://defense.engineer/policy/data-deletion.html) |
| Terms of use | Supplemental teaching-use terms and platform-EULA reference | `terms-of-service.html` | [Open](https://defense.engineer/policy/terms-of-service.html) |

## Publication and maintenance

- Every page is self-contained HTML with inline styles; no JavaScript, external font, form, login, PDF or editable-document service is required. The marketing screenshot is embedded in its HTML.
- All pages contain English and Thai text, an effective date, app identity and the support contact `la@defense.engineer`.
- Privacy wording includes Android Firebase native registration processing. Do not replace it with a blanket no-collection claim merely because the app's JavaScript has no network request.
- Keep local storage, OS backups, exported recipient copies, support email and provider-held identifiers separate when explaining deletion.
- The pages do not complete Google Play's seven console declarations or Apple's App Privacy form. They do not assert a store approval or public app release.
- A privacy-policy URL must also be reachable inside each submitted app. Publishing this directory cannot add that link to an already built binary.
- Terms are supplemental information. A custom Apple EULA is a separate App Store Connect setting; this repository does not configure it.
- Preserve the repository's existing domain, publishing source and unrelated pages. Verify HTTPS200 responses and final contents after each Pages build.
- Keep filenames lowercase and hyphenated. For another app, use a new app-specific prefix or subdirectory; do not repurpose these stable B2L URLs.

## Store identity fields

App Store developer: **Tanat Tonguthaisri**. Google Play developer display name: **Harness Engineer**. Intended audience selected by the owner: **13–15, 16–17 and adults**; content ratings remain a separate questionnaire result.

Copyright field text prepared from the supplied owner name and this2026 app project: `2026 Tanat Tonguthaisri`. This is plain text, not a URL, and does not claim ownership of third-party software or fonts.

Effective policy version: **2026-10-24**, covering bundled teaching content and optional Microsoft report features where available in the installed version. The pages do not announce a new public release; the report-enabled journey is described as a new testing version on the marketing page. Reassess both policy and store declarations when SDKs or app behavior change.

## Readable contact details without JavaScript

The HTML uses Cloudflare-documented `email_off` comment markers so the public support email and mailto links remain readable without a decoder script. This changes only these pages, not the domain-wide setting. A restrictive Content Security Policy blocks client-side scripts, including any analytics beacon added by the hosting provider. Hosting/security request metadata is still covered in the privacy policy.


## Optional Microsoft report update (2026-10-24)

- Core bundled teaching content remains offline and requires no B2L account or Microsoft sign-in. External Power BI access requires internet and an authorized Microsoft account; the SharePoint package can require separate sign-in and permissions.
- External figures are separate from the fictional teaching dataset. Microsoft and the relevant organization govern their service processing, retention and access. Deleting B2L app data is not a provider deletion request.
- The HTML keeps the existing Android Firebase disclosures, no-JavaScript CSP, inline styling, public identities and readable contact markers.
- Marketing describes the five-chapter/report-enabled experience as a new testing version. No completed test, store approval or new public-release claim is made.
- The historical 2026-10-15 data-practice records and generator were not rewritten. The old generator does not contain this update; do not run it over these reviewed pages. Reconcile a future generator against this policy directory before generating again.
- Local publication preparation and validation are recorded in the coordinating app's `docs/release-20261024/POLICY_PUBLICATION_PREP.md`. Commit and push remain the coordinating host's responsibility after review.
