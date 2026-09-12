import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { consumeUrlParameters } from "./config";
import "./styles.css";

// BEFORE React renders: pull ?api= and ?key= out of the URL, persist them,
// and strip them from the address bar. Doing this first means no component
// ever observes a URL still carrying the key.
//
// ORDERING WITH THE ROUTER (added in P1-B): this call uses
// window.history.replaceState() directly, then <App> constructs
// <BrowserRouter> further down the tree. BrowserRouter reads
// window.location at the moment it mounts to seed its own history stack --
// which happens after this line has already run and already rewritten the
// URL. So the router only ever sees the post-strip path (with the api/key
// params gone but the pathname and hash intact); there is no race and
// nothing to reconcile between the two. Verified manually -- see the P1-B
// change report for the click-through.
consumeUrlParameters();

const container = document.getElementById("root");
if (container === null) throw new Error("#root is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
