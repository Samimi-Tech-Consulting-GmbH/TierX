const { validate } = require("@forge/manifest");

validate(false)
  .then((result) => {
    for (const entry of result.errors || []) {
      process.stderr.write(`${entry.level}: ${entry.message}\n`);
    }
    if (!result.success) process.exitCode = 1;
  })
  .catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
