# Reference-page exercise

The included [reference page](../examples/reference-app.html) is a self-contained browser exercise. It verifies that the browser and evidence-capture procedure work; it does not demonstrate OpenAgents delivery or a real model call.

1. Open the HTML file in a browser automation tool. If file URLs are unavailable, serve only the example directory through a temporary local HTTP server.
2. Inspect the page, use its input and button controls, and wait for the displayed result.
3. Capture the resulting UI state and inspect console errors. Save the screenshot and reproduction notes outside the candidate's tracked source.
4. For a negative control, use a disposable copy with the expected state change disabled. The same assertion should fail; do not modify the checked candidate to manufacture evidence.
5. Stop any temporary server after the exercise and report the browser/tool version and observed result.

For an actual application, fill in the [runbook template](_runbook-template.md) with that application's endpoints, startup commands, readiness checks, and expected behavior.
