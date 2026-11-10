import { clone, replay, validateAlerts, writePath } from "./scenario.mjs";

export function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted)
      return reject(new DOMException("Aborted", "AbortError"));
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", abort, { once: true });
  });
}
export class ScenarioRunner {
  constructor({
    submit,
    generate,
    record = () => {},
    changed = () => {},
    accepted = () => {},
    sleep = delay,
    clock = () => Date.now(),
    uuid = () => crypto.randomUUID(),
  }) {
    Object.assign(this, {
      submit,
      generate,
      record,
      changed,
      accepted,
      sleep,
      clock,
      uuid,
    });
    this.state = "IDLE";
    this.counts = {
      generated: 0,
      accepted: 0,
      rejected: 0,
      failed: 0,
      pending: 0,
    };
  }
  snapshot() {
    return {
      state: this.state,
      counts: { ...this.counts },
      error: this.error || "",
      completed: this.completed || 0,
    };
  }
  emit() {
    this.changed(this.snapshot());
  }
  pause() {
    if (this.state === "RUNNING") {
      this.state = "PAUSED";
      this.controller?.abort();
      this.emit();
    }
  }
  resume() {
    if (this.state === "PAUSED") {
      this.state = "RUNNING";
      this.emit();
      this.unpause?.();
    }
  }
  stop(state = "STOPPED") {
    if (["RUNNING", "PAUSED"].includes(this.state)) {
      this.state = state;
      this.controller?.abort();
      this.unpause?.();
      this.emit();
    }
  }
  async start(scenario, { continuous = false, once = false } = {}) {
    if (["RUNNING", "PAUSED"].includes(this.state))
      throw new Error("A scenario is already running.");
    this.scenario = clone(scenario);
    this.state = "RUNNING";
    this.error = "";
    this.completed = 0;
    this.pending = null;
    this.nextAt = 0;
    this.counts = {
      generated: continuous ? 0 : scenario.alerts.length,
      accepted: 0,
      rejected: 0,
      failed: 0,
      pending: 0,
    };
    const limit = once ? scenario.alerts.length : scenario.settings.total;
    let queue = continuous ? [] : clone(scenario.alerts),
      index = 0;
    const deadline = this.clock() + scenario.settings.duration_minutes * 60000;
    const expiry = setTimeout(
      () => this.stop("TIMED_OUT"),
      scenario.settings.duration_minutes * 60000,
    );
    this.emit();
    try {
      while (
        ["RUNNING", "PAUSED"].includes(this.state) &&
        this.completed < limit
      ) {
        if (this.clock() >= deadline) {
          this.stop("TIMED_OUT");
          break;
        }
        if (this.state === "PAUSED") {
          await new Promise((resolve) => {
            this.unpause = resolve;
          });
          continue;
        }
        this.controller = new AbortController();
        const signal = this.controller.signal;
        try {
          if (this.nextAt > this.clock())
            await this.sleep(
              Math.min(this.nextAt, deadline) - this.clock(),
              signal,
            );
          if (signal.aborted || this.clock() >= deadline) continue;
          if (!this.pending) {
            if (continuous && !queue.length) {
              const generated = await this.generate(
                Math.min(5, limit - this.completed),
                signal,
              );
              if (signal.aborted) continue;
              queue = clone(
                validateAlerts(generated, scenario.schema, scenario.negative),
              );
              this.counts.generated += queue.length;
              this.emit();
            }
            const source = continuous
              ? queue.shift()
              : queue[index++ % queue.length];
            const identity = this.uuid();
            this.pending = {
              identity,
              payload: replay(
                source,
                scenario.settings,
                identity,
                new Date(this.clock()).toISOString(),
              ),
              attempts: 0,
            };
            if (scenario.negative)
              writePath(
                this.pending.payload,
                scenario.missing_path,
                undefined,
                true,
              );
            this.counts.pending = 1;
            this.emit();
          }
          let result,
            failure = new Error("Submission retry allowance exhausted.");
          for (let attempt = this.pending.attempts; attempt < 4; attempt++) {
            if (signal.aborted) break;
            this.pending.attempts++;
            try {
              result = await this.submit(
                this.pending.payload,
                this.pending.identity,
                signal,
              );
              failure = null;
              break;
            } catch (error) {
              if (signal.aborted) throw error;
              failure = error;
              const transient =
                !error.status ||
                [408, 429].includes(error.status) ||
                error.status >= 500;
              if (!transient || attempt === 3) break;
              await this.sleep(500 * 2 ** attempt, signal);
            }
          }
          if (signal.aborted) continue;
          const outcome = {
            delivery_id: this.pending.identity,
            timestamp: new Date(this.clock()).toISOString(),
            attempts: this.pending.attempts,
          };
          if (failure) {
            const rejected = failure.status >= 400 && failure.status < 500;
            this.counts[rejected ? "rejected" : "failed"]++;
            Object.assign(outcome, {
              state: rejected ? "REJECTED" : "FAILED",
              status: failure.status || 0,
            });
            if ([400, 401, 403, 404, 405, 410].includes(failure.status)) {
              this.error =
                "Authentication or workflow routing failed; run stopped.";
              this.state = "FAILED";
            }
          } else {
            this.counts.accepted++;
            Object.assign(outcome, {
              state: "ACCEPTED",
              alert_id: result.alert_id,
              run_id: result.run_id,
            });
            this.accepted(result);
          }
          await this.record({ ...outcome, payload: this.pending.payload });
          this.completed++;
          this.pending = null;
          this.counts.pending = 0;
          this.emit();
          this.nextAt =
            this.clock() + scenario.settings.interval_seconds * 1000;
        } catch (error) {
          if (signal.aborted) continue;
          this.error = error.message || "Scenario run failed.";
          this.state = "FAILED";
          this.emit();
        }
      }
      if (this.state === "RUNNING") this.state = "COMPLETED";
    } finally {
      clearTimeout(expiry);
      if (this.pending) {
        await this.record({
          delivery_id: this.pending.identity,
          payload: this.pending.payload,
          state: "UNKNOWN",
          timestamp: new Date(this.clock()).toISOString(),
          attempts: this.pending.attempts,
        });
        this.pending = null;
      }
      this.counts.pending = 0;
      this.emit();
    }
    return this.snapshot();
  }
}
