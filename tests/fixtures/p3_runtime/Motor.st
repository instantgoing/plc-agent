FUNCTION_BLOCK FB_Motor
VAR_INPUT
    Start : BOOL;
    Stop : BOOL;
END_VAR
VAR_OUTPUT
    Running : BOOL;
END_VAR
Running := Start AND NOT Stop;
END_FUNCTION_BLOCK

PROGRAM MAIN
VAR
    StartPB AT %IX0.0 : BOOL;
    StopPB AT %IX0.1 : BOOL;
    FaultPB AT %IX0.2 : BOOL;
    Motor AT %QX0.0 : BOOL;
END_VAR
VAR
    MotorController : FB_Motor;
END_VAR
MotorController(Start := StartPB, Stop := StopPB);
Motor := MotorController.Running;
END_PROGRAM

CONFIGURATION Config0
    RESOURCE Res0 ON PLC
        TASK MainTask(INTERVAL := T#20ms, PRIORITY := 0);
        PROGRAM Inst0 WITH MainTask : MAIN;
    END_RESOURCE
END_CONFIGURATION
