export function isCurrentDownloadUi(config, candidate, waitStartedAt) {
  const issuedAt = Number(candidate?.receiptIssuedAt ?? candidate?.startedAt);
  return candidate?.runId === config?.runId &&
    Number.isFinite(issuedAt) &&
    issuedAt >= Number(waitStartedAt) - 2000;
}

export function assertJinshaReleased(candidate) {
  if (candidate?.jinshaResourceReleased !== true ||
      !Number.isFinite(Number(candidate?.jinshaReleasedAt))) {
    throw new Error('jinsha-not-released');
  }
}
