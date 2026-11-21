package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.TaskHandler;
import io.github.iy88.project1.messaging.TaskSchedules;

/** S1 task adapter for single-side confirmation timeout. */
public class TradeTimeoutHandler implements TaskHandler {
    public static final String KIND = "trade.timeout";

    private final TradeApplication application;

    public TradeTimeoutHandler(TradeApplication application) {
        this.application = application;
    }

    @Override
    public String kind() {
        return KIND;
    }

    @Override
    public LockPlan prepare(ExecutionContext context, TaskSchedules.Task task) {
        return application.timeoutPlan(task.spec().source().id());
    }

    @Override
    public void lockAndQualify(WriteTransaction transaction, TaskSchedules.Task task) {
        application.lockForTimeout(transaction, task.spec().source().id());
    }

    @Override
    public boolean isApplicable(TaskSchedules.Task task) {
        return application.timeoutApplicable(task.spec().source().id(), task.spec().sourceVersion());
    }

    @Override
    public void execute(WriteTransaction transaction, TaskSchedules.Task task) {
        application.applyTimeout(transaction, transaction.context(), task.spec().source().id(),
                task.spec().sourceVersion());
    }
}
