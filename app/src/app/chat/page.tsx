import { ComingSoon } from "@/components/layout/coming-soon";

export default function ChatPage() {
  return (
    <ComingSoon
      currentPath="/chat"
      heading="ai chat"
      body="AI chat is deferred per design spec §9; built last."
      planName="DEFERRED"
    />
  );
}
