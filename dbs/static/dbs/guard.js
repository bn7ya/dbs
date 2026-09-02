(function () {
  var script = document.getElementById("dbs-guard");
  if (!script) { return; }
  var url = script.dataset.url;
  var login = script.dataset.login;
  var wantsLocation = false;
  var timer = null;

  function token() {
    var field = document.querySelector("[name=csrfmiddlewaretoken]");
    if (field) { return field.value; }
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function locate() {
    return new Promise(function (resolve) {
      if (!wantsLocation || !navigator.geolocation) { resolve(null); return; }
      navigator.geolocation.getCurrentPosition(
        function (position) {
          resolve({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: position.coords.accuracy
          });
        },
        function () { resolve(null); },
        { timeout: 5000, maximumAge: 300000 }
      );
    });
  }

  function check() {
    locate().then(function (location) {
      return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": token(),
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({ location: location })
      });
    }).then(function (response) {
      if (response.status === 401) { window.location = login; return null; }
      return response.json();
    }).then(function (data) {
      if (!data) { return; }
      wantsLocation = Boolean(data.wants_location);
      if (data.action === "logout") { window.location = login; return; }
      if (data.action === "reauth") { announce(data.reasons); }
      schedule((data.poll_after || 15) * 1000);
    }).catch(function () { schedule(60000); });
  }

  function announce(reasons) {
    var existing = document.getElementById("dbs-guard-note");
    if (existing) { existing.remove(); }
    var note = document.createElement("div");
    note.id = "dbs-guard-note";
    note.className = "errornote";
    note.textContent = "DBS flagged this session: " + (reasons || []).join("; ");
    var content = document.getElementById("content") || document.body;
    content.insertBefore(note, content.firstChild);
  }

  function schedule(delay) {
    window.clearTimeout(timer);
    timer = window.setTimeout(check, delay);
  }

  schedule(2000);
})();
