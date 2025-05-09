type Props = { progress: number }
export default function ProgressBar({ progress }: Props) {
  return (
    <div className="w-full bg-gray-200 rounded-full h-3">
      <div
        className="bg-indigo-500 h-3 rounded-full transition-all"
        style={{ width: `${progress}%` }}
      />
    </div>
  );
}
