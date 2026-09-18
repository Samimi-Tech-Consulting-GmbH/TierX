import Link from "next/link";

function releaseInfo() {
  const version = process.env.NEXT_PUBLIC_TIERX_RELEASE_VERSION ?? process.env.NEXT_PUBLIC_APP_RELEASE_VERSION ?? "development";
  const sha = process.env.NEXT_PUBLIC_TIERX_RELEASE_SHA ?? process.env.NEXT_PUBLIC_APP_RELEASE_SHA ?? "development";
  const tag = version === "development" ? null : `v${version.replace(/^v/, "")}`;
  const repositoryUrl = process.env.NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY?.replace(/\/$/, "");
  if (tag && !repositoryUrl) {
    throw new Error("A release build requires NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY");
  }
  return {
    version,
    sha,
    sourceUrl: repositoryUrl ? (tag ? `${repositoryUrl}/tree/${tag}` : repositoryUrl) : null,
    documentationUrl: repositoryUrl ? `${repositoryUrl}/blob/${tag ?? "main"}/SOURCE.md` : null,
  };
}

export default function SourceCodePage() {
  const release = releaseInfo();
  return (
    <main className="mx-auto min-h-screen max-w-3xl px-6 py-16 text-foreground">
      <h1 className="text-3xl font-semibold">TierX source code</h1>
      <p className="mt-5 text-muted-foreground">
        TierX is licensed under GNU AGPL version 3 only. The corresponding
        source for this deployed build, including build and installation
        documentation, is available at the tagged source link below.
      </p>
      <dl className="mt-8 grid gap-3 rounded-xl border p-6 sm:grid-cols-[10rem_1fr]">
        <dt>Version</dt><dd className="font-mono">{release.version}</dd>
        <dt>Git revision</dt><dd className="break-all font-mono">{release.sha}</dd>
        <dt>License</dt><dd>AGPL-3.0-only</dd>
      </dl>
      <div className="mt-8 flex flex-wrap gap-4">
        {release.sourceUrl && <a className="text-primary underline" href={release.sourceUrl}>Tagged corresponding source</a>}
        {release.documentationUrl && <a className="text-primary underline" href={release.documentationUrl}>Build and installation guide</a>}
        {!release.sourceUrl && <p>Source repository is not configured for this development build.</p>}
        <Link className="text-primary underline" href="/login">Return to TierX</Link>
      </div>
    </main>
  );
}
