import { useCallback, useEffect, useState } from "react";
import { getUploadPolicy, listDocuments } from "../api/client.js";
import UploadPanel from "./UploadPanel.jsx";
import DocumentList from "./DocumentList.jsx";
import DocumentDetail from "./DocumentDetail.jsx";

const PAGE_SIZE = 20;

export default function DocumentsPage() {
  const [policy, setPolicy] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState(null);

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

  function handleUploaded(created) {
    setSelectedId(created.id);
    if (offset === 0) load(0);
    else setOffset(0);
  }

  return (
    <div className="space-y-6">
      <UploadPanel policy={policy} onUploaded={handleUploaded} />
      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <DocumentList
          data={data}
          loading={loading}
          error={error}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onPage={setOffset}
        />
        <DocumentDetail documentId={selectedId} />
      </div>
    </div>
  );
}
