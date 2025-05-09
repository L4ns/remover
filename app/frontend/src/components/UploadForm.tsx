import { useState, useEffect } from "react";
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

    if (file) {
      await uploadWithProgress(file);
    } else if (link) {
      await processLink(link);
    } else {
      setError("Masukkan link atau pilih file.");
      setLoading(false);
    }
  };

  const uploadWithProgress = async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "http://localhost:5000/upload", true);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        setProgress(percent);
      }
    };

    xhr.onload = () => {
      setLoading(false);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          if (data.stream_url || data.result_url) {
            setResultUrl(data.stream_url || data.result_url);
          } else {
            setError(data.error || "Gagal memproses video");
          }
        } catch {
          setError("Respon server tidak valid.");
        }
      } else {
        setError(`Gagal upload. Status: ${xhr.status}`);
      }
    };

    xhr.onerror = () => {
      setLoading(false);
      setError("Terjadi kesalahan saat upload.");
    };

    xhr.send(formData);
  };

  const processLink = async (link: string) => {
    try {
      const res = await fetch("http://localhost:5000/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: link }),
      });

      const data = await res.json();

      if (res.ok) {
        if (data.stream_url || data.result_url) {
          setResultUrl(data.stream_url || data.result_url);
        } else {
          setError(data.error || "Gagal memproses video.");
        }
      } else {
        setError(data.error || "Proses gagal.");
      }
    } catch (err) {
      setError("Gagal terhubung ke server.");
    } finally {
      setLoading(false);
      setProgress(100);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full flex flex-col gap-4">
      <input
        type="file"
        accept="video/*"
        onChange={(e) => {
          setFile(e.target.files?.[0] || null);
          setLink("");
        }}
        className="border p-2 rounded"
      />
      <div className="text-center text-gray-500">atau</div>
      <input
        type="text"
        placeholder="Paste link video (TikTok, IG, dst)"
        value={link}
        onChange={(e) => {
          setLink(e.target.value);
          setFile(null);
        }}
        className="border p-2 rounded"
      />
      <button
        type="submit"
        className="bg-indigo-600 text-white py-2 rounded hover:bg-indigo-700 transition disabled:opacity-50"
        disabled={loading}
      >
        {loading ? "Memproses..." : "Proses Video"}
      </button>
      {loading && <ProgressBar progress={progress} />}
      {resultUrl && (
        <div className="mt-4">
          <video src={resultUrl} controls className="w-full rounded shadow" />
          <a
            href={resultUrl}
            download
            className="block mt-2 text-indigo-600 underline"
          >
            Download Hasil
          </a>
        </div>
      )}
      {error && <div className="text-red-500">{error}</div>}
    </form>
  );
}
