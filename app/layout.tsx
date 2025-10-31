export const metadata = {
  title: "Qwen3 Omni Web",
  description: "Chat with text + audio and camera preview"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: 'ui-sans-serif, system-ui, -apple-system', margin: 0, padding: 16 }}>
        {children}
      </body>
    </html>
  );
}

