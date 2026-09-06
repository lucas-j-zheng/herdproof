# HerdProof website

A production static website explaining the agricultural lending use case,
showing real prototype output and measured technical evidence, and outlining a
proposed lender/ranch pilot. It includes sample-photo review and real browser inference using an ONNX export.
The Python survey/world server runs separately.

## Development

Use Node.js 22.13+ and pnpm. The existing pnpm-lock.yaml pins dependencies.

```
pnpm install --frozen-lockfile
pnpm dev
pnpm build
```

The app uses the Sites Vinext starter with a static export. Public content is in
app/page.tsx; styles in app/globals.css; sources and download in public/evidence.
The live Sites project is recorded in .openai/hosting.json.
Browser demo components are in components/demo, with tiled inference in lib/detect.ts.
The model, ONNX Runtime Web assets and sample photos are under public/demo.

## Vercel deployment

The website is also configured for a static Vercel deployment. With the installed
Vercel CLI linked to the HerdProof project, run:

```
pnpm run build:vercel
vercel deploy --prebuilt --prod
```

`build:vercel` copies only the compiled public site into `.vercel/output/static`
and writes the Vercel Build Output API configuration. The Python application,
original farm uploads and local survey state are not part of this website.
`vercel.json` also specifies the locked install and static output for remote builds.

Image assets are existing metadata-free review copies, credited on the website
under CC BY 4.0. No inference results, lending outcomes, or customer relationships
have been fabricated. The sample business context is explicitly illustrative.
