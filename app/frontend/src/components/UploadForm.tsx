// ... existing code ...
import { useState } from "react";
import ProgressBar from "./ProgressBar";

export default function UploadForm() {
  const [link, setLink] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [resultUrl, setResultUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setProgress(0);
    setResultUrl("");
    setError("");
    setLoading(true);

    try {
      let res, data;
      if (file) {
        // Upload file ke endpoint /upload
        const formData = new FormData();
        formData.append("file", file);
        res = await fetch("http://localhost:5000/upload", {
          method: "POST",
          body: formData,
        });
      } else if (link) {
        // Proses link ke endpoint /process
        res = await fetch("http://localhost:5000/process", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: link }),
        });
      } else {
        setError("Masukkan link atau pilih file.");
        setLoading(false);
        return;
      }
      data = await res.json();
      if (data.result_url) {
        setResultUrl(data.result_url);
      } else {
        setError(data.error || "Gagal memproses video");
      }
    } catch {
      setError("Gagal terhubung ke server");
    }
    setLoading(false);
  };

  return (
    <form onSubmit={handleSubmit} className="w-full flex flex-col gap-4">
      <input
        type="file"
        accept="video/*"
        onChange={e => setFile(e.target.files?.[0] || null)}
        className="border p-2 rounded"
      />
      <div className="text-center text-gray-500">atau</div>
      <input
        type="text"
        placeholder="Paste link video (TikTok, IG, dst)"
        value={link}
        onChange={e => setLink(e.target.value)}
        className="border p-2 rounded"
      />
      <button
        type="submit"
        className="bg-indigo-600 text-white py-2 rounded hover:bg-indigo-700 transition"
        disabled={loading}
      >
        {loading ? "Memproses..." : "Proses Video"}
      </button>
      {loading && <ProgressBar progress={progress} />}
      {resultUrl && (
        <div className="mt-4">
          <video src={resultUrl} controls className="w-full rounded shadow" />
          <a href={resultUrl} download className="block mt-2 text-indigo-600 underline">
            Download Hasil
          </a>
        </div>
      )}
      {error && <div className="text-red-500">{error}</div>}
    </form>
  );
}
// ... existing code ...
