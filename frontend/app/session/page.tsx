"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { SessionView } from "@/components/SessionView";

function Session() {
  const params = useSearchParams();
  // From the Notebooks page: add notes to one notebook, or recite it straight away.
  return (
    <SessionView
      variant="session"
      openNotebookId={params.get("notebook")}
      reciteNotebookId={params.get("recite")}
    />
  );
}

export default function SessionPage() {
  return (
    <Suspense>
      <Session />
    </Suspense>
  );
}
