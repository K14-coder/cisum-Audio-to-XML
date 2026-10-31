import { useEffect, useState } from "react";
import { api, errorMessage } from "../api/client";
import type { RightsNotice as Notice } from "../api/types";
import { RightsNotice } from "../components/RightsNotice";
import { DMCA_EMAIL } from "../config";

export function RightsPage() {
  const [notice, setNotice] = useState<Notice | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .rightsNotice()
      .then(setNotice)
      .catch((err) => setError(errorMessage(err)));
  }, []);

  return (
    <div className="page narrow prose">
      <h1>Rights notice</h1>
      <p>Everyone agrees to this notice, by ticking a box, before each upload.</p>
      {error && <p className="error-text">{error}</p>}
      {notice && <RightsNotice notice={notice} />}
      {notice && <p className="muted small-text">Version {notice.version}</p>}
    </div>
  );
}

export function TakedownPage() {
  return (
    <div className="page narrow prose">
      <h1>Reporting copyright infringement</h1>
      <p>
        Cisum turns recordings that users upload into piano arrangements. Users must confirm they have the rights to
        each recording and to share what they create. If a shared arrangement infringes your rights, tell us and we'll
        remove it.
      </p>
      <h2>The quickest way: the Report button</h2>
      <p>
        Every shared arrangement page has a <strong>Report</strong> button. Choose “It infringes my copyright”, describe
        the work, and confirm the statement. The arrangement is hidden right away while we review the report.
      </p>
      <h2>By email</h2>
      <p>
        You can also send a notice to our designated agent at <a href={`mailto:${DMCA_EMAIL}`}>{DMCA_EMAIL}</a>. Please
        include:
      </p>
      <ul>
        <li>the link to the shared arrangement;</li>
        <li>the work you believe is infringed (title and writer(s));</li>
        <li>your name, address, phone number and email;</li>
        <li>
          a statement that you have a good-faith belief the use is not authorized by the copyright owner, its agent, or
          the law;
        </li>
        <li>
          a statement that the information is accurate and, under penalty of perjury, that you are the owner or
          authorized to act for the owner;
        </li>
        <li>your physical or electronic signature.</li>
      </ul>
      <h2>What happens next</h2>
      <p>
        When a report is upheld, every share of that song is taken down and the uploader receives a strike. Accounts
        that reach the strike limit are closed. If you believe your arrangement was removed by mistake, send a
        counter-notice to <a href={`mailto:${DMCA_EMAIL}`}>{DMCA_EMAIL}</a>.
      </p>
    </div>
  );
}
