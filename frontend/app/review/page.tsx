"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { SessionView } from "@/components/SessionView";

function Review() {
  const note = useSearchParams().get("note");
  // Opens straight into a quiz: of what is due, or practice on one note from the memory map.
  return <SessionView variant="review" autoQuiz quizNoteId={note} />;
}

export default function ReviewPage() {
  return (
    <Suspense>
      <Review />
    </Suspense>
  );
}
