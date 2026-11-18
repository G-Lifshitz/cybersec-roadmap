// Where the UI finds the two services. This file holds the local compose values;
// the CD pipeline overwrites it with the Azure URLs when it uploads the UI.
window.APP_CONFIG = {
  ROADMAP_URL: "http://localhost:8001",
  PROGRESS_URL: "http://localhost:8002",
};
