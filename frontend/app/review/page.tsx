"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { SessionView } from "@/components/SessionView";

function Review() {
  const params = useSearchParams();
  // Opens straight into a quiz: what is due, practice on one note (from the map or stats), or the
  // daily brief (from the "Your brief is ready" banner).
  return (
    <SessionView
      variant="review"
      autoQuiz
      quizNoteId={params.get("note")}
      briefId={params.get("brief")}
    />
  );
}

export default function ReviewPage() {
  return (
    <Suspense>
      <Review />
    </Suspense>
  );
}
