# Terminal tape authoring (VHS)

`.tape` files run in a real shell. Avoid real long-running commands in demos.

## Safe pattern: simulate output with `echo`

Prefer:

```tape
Type "echo '$ python app.py --serve'"
Enter
Type "echo 'Starting server on :8080'"
Enter
```

Avoid in tapes unless you really want to execute them:
- `python ...`
- `curl localhost ...`
- `npm start`, `docker ...`, `kubectl ...`

Useful checks:
- `docgen tape-lint` (warn on risky command patterns)
- `docgen vhs --strict` (fails on common shell error output)
