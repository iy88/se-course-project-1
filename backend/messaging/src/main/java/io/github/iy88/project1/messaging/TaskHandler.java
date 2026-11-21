package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;

public interface TaskHandler {
    String kind();

    LockPlan prepare(ExecutionContext context, TaskSchedules.Task task);

    void lockAndQualify(WriteTransaction transaction, TaskSchedules.Task task);

    boolean isApplicable(TaskSchedules.Task task);

    void execute(WriteTransaction transaction, TaskSchedules.Task task);
}
