/**
 * Application shell. M0 scope: an accessible static shell only — routing,
 * the auth shell and feature views are built from M1 onwards. WCAG 2.2 AA
 * is a hard requirement: semantic landmarks, keyboard navigability and
 * axe-core checks apply from the first commit.
 */
export function App(): JSX.Element {
  return (
    <>
      <header>
        <h1>TenderScore</h1>
      </header>
      <main>
        <p>AI scores, humans moderate, AI documents.</p>
        <p>
          Evaluation workspace under construction. Sign-in and procurement
          set-up arrive in a later milestone.
        </p>
      </main>
      <footer>
        <p>Private pre-clearance build — synthetic data only.</p>
      </footer>
    </>
  );
}
