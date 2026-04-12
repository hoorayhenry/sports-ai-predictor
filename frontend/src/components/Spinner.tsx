export default function Spinner({ size = 24 }: { size?: number }) {
  return (
    <div
      className="animate-spin rounded-full border-2 border-slate-600 border-t-sky-500 mx-auto"
      style={{ width: size, height: size }}
    />
  );
}
