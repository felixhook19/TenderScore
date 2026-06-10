/**
 * Application shell: sign-in, procurement list, moderation queue and the
 * recommendation decision view. WCAG 2.2 AA is a hard requirement —
 * semantic landmarks, labelled controls, keyboard operability throughout.
 */
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  listProcurements,
  me,
  moderationQueue,
  recommendationDetail,
  setSessionToken,
} from "../api/client";
import type {
  Me,
  Procurement,
  QueueEntry,
  RecommendationDetail,
} from "../api/types";
import { LoginForm } from "../features/auth/LoginForm";
import { ModerationQueue } from "../features/moderation/ModerationQueue";
import { RecommendationView } from "../features/moderation/RecommendationView";
import { ProcurementList } from "../features/procurements/ProcurementList";

type View =
  | { name: "procurements" }
  | { name: "queue"; procurement: Procurement }
  | { name: "recommendation"; procurement: Procurement; detail: RecommendationDetail };

export function App(): JSX.Element {
  const [user, setUser] = useState<Me | null>(null);
  const [view, setView] = useState<View>({ name: "procurements" });
  const [procurements, setProcurements] = useState<Procurement[]>([]);
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refreshProcurements = useCallback(async (): Promise<void> => {
    try {
      setProcurements(await listProcurements());
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "The procurement list could not be loaded.",
      );
    }
  }, []);

  useEffect(() => {
    if (user !== null) void refreshProcurements();
  }, [user, refreshProcurements]);

  async function handleAuthenticated(token: string): Promise<void> {
    setSessionToken(token);
    try {
      setUser(await me());
      setError(null);
    } catch {
      setSessionToken(null);
      setError("Your session could not be established. Please sign in again.");
    }
  }

  async function openQueue(procurement: Procurement): Promise<void> {
    try {
      setQueue(await moderationQueue(procurement.id));
      setView({ name: "queue", procurement });
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "The moderation queue could not be loaded.",
      );
    }
  }

  async function openRecommendation(
    procurement: Procurement,
    entry: QueueEntry,
  ): Promise<void> {
    try {
      const detail = await recommendationDetail(entry.recommendation_id);
      setView({ name: "recommendation", procurement, detail });
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "The recommendation could not be loaded.",
      );
    }
  }

  function signOut(): void {
    setSessionToken(null);
    setUser(null);
    setView({ name: "procurements" });
    setProcurements([]);
    setQueue([]);
  }

  return (
    <>
      <header>
        <h1>TenderScore</h1>
        {user !== null && (
          <p>
            Signed in as {user.display_name} ({user.email}){" "}
            <button type="button" onClick={signOut}>
              Sign out
            </button>
          </p>
        )}
      </header>
      <main>
        {error !== null && <p role="alert">{error}</p>}
        {user === null ? (
          <LoginForm onAuthenticated={(token) => void handleAuthenticated(token)} />
        ) : view.name === "procurements" ? (
          <ProcurementList
            procurements={procurements}
            onOpen={(procurement) => void openQueue(procurement)}
          />
        ) : view.name === "queue" ? (
          <ModerationQueue
            procurementTitle={view.procurement.title}
            entries={queue}
            onOpen={(entry) => void openRecommendation(view.procurement, entry)}
            onBack={() => setView({ name: "procurements" })}
          />
        ) : (
          <RecommendationView
            detail={view.detail}
            onDecided={() => void openQueue(view.procurement)}
            onBack={() => void openQueue(view.procurement)}
          />
        )}
      </main>
      <footer>
        <p>
          AI scores, humans moderate, AI documents. Private pre-clearance build
          {" — "}synthetic data only.
        </p>
      </footer>
    </>
  );
}
