import { useCallback, useEffect, useState } from "react";
import { getUploadPolicy, listDocuments, startProcessing } from "../api/client.js";
import UploadPanel from "./UploadPanel.jsx";
import DocumentList from "./DocumentList.jsx";
import DocumentDetail from "./DocumentDetail.jsx";
import { inProgress } from "../utils/processing.js";

const PAGE_SIZE = 20;

export default function DocumentsPage() {
  const [policy, setPolicy] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async (pageOffset, signal) => {
    setLoading(true);
    try {
      setData(await listDocuments({ limit: PAGE_SIZE, offset: pageOffset }, { signal }));
      setError(null);
    } catch (err) {
      if (err.name === "AbortError") return;
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getUploadPolicy({ signal: controller.signal })
      .then(setPolicy)
      .catch(() => {}); // the server still validates; the list shows connectivity errors
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(offset, controller.signal);
    return () => controller.abort();
  }, [load, offset]);

  async function handleUploaded(created) {
    setNotice(null);
    try {
      await startProcessing(created.id); // text extraction, then tables and images, start automatically after upload
    } catch (err) {
      setNotice(`The file was uploaded, but text extraction could not be started: ${err.message}`);
    }
    setSelectedId(created.id);
    if (offset === 0) load(0);
    else setOffset(0);
  }

  const refreshList = useCallback(() => load(offset), [load, offset]);

  // Keep the list current while any document is queued or processing (e.g. right after an upload).
  const anyInProgress = data?.items?.some(inProgress) ?? false;
  useEffect(() => {
    if (!anyInProgress) return undefined;
    const timer = setTimeout(() => load(offset), 2000);
    return () => clearTimeout(timer);
  }, [anyInProgress, data, load, offset]);

  return (
    <div className="space-y-6">
      <UploadPanel policy={policy} onUploaded={handleUploaded} />
      {notice && (
        <p role="alert" className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {notice}
        </p>
      )}
      <DocumentList
        data={data}
        loading={loading}
        error={error}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onPage={setOffset}
      />
      <DocumentDetail documentId={selectedId} onProcessingChange={refreshList} />
    </div>
  );
}
