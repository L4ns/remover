import UploadForm from "../components/UploadForm";

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-100 to-indigo-200 flex flex-col items-center justify-center">
      <main className="w-full max-w-xl p-8 bg-white rounded-xl shadow-lg flex flex-col items-center">
        <h1 className="text-3xl font-bold mb-4 text-indigo-700">Remove Watermark Video</h1>
        <p className="mb-6 text-gray-600 text-center">
          Upload video atau masukkan link dari TikTok, Instagram, Twitter, Facebook, Telegram, atau Cloud.<br />
          Proses otomatis dengan AI, hasil cepat dan natural!
        </p>
        <UploadForm />
      </main>
    </div>
  );
}
