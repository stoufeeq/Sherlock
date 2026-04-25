       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEDGER.
      *****************************************************************
      * Nightly ledger posting batch.
      * Reads flat postings file, writes account balances to Postgres.
      * DB dependency: schema LEDGER, table BALANCES
      *   account_id  VARCHAR(64)
      *   amount      NUMERIC(19,4)
      *   currency    VARCHAR(3)
      *   posted_at   TIMESTAMPTZ
      *****************************************************************
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT POSTINGS-FILE ASSIGN TO "/shared/postings/POSTINGS.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE ASSIGN TO "/shared/reports/LEDGER.RPT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD POSTINGS-FILE.
       01 POSTING-REC.
           05 PR-ACCOUNT-ID    PIC X(16).
           05 PR-AMOUNT        PIC S9(13)V9999.
           05 PR-CURRENCY      PIC X(3).

       FD REPORT-FILE.
       01 REPORT-LINE          PIC X(120).

       WORKING-STORAGE SECTION.
       01 WS-EOF               PIC X VALUE 'N'.
       01 WS-TOTAL-COUNT       PIC 9(9) VALUE 0.

       EXEC SQL
           INCLUDE SQLCA
       END-EXEC.

       EXEC SQL BEGIN DECLARE SECTION END-EXEC.
       01 DB-ACCOUNT-ID        PIC X(64).
       01 DB-AMOUNT            PIC S9(13)V9999.
       01 DB-CURRENCY          PIC X(3).
       EXEC SQL END DECLARE SECTION END-EXEC.

       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL CONNECT TO 'banking' USER 'banking' USING 'banking'
           END-EXEC.

           OPEN INPUT POSTINGS-FILE.
           OPEN OUTPUT REPORT-FILE.

           PERFORM UNTIL WS-EOF = 'Y'
               READ POSTINGS-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM POST-ONE
               END-READ
           END-PERFORM.

           MOVE SPACES TO REPORT-LINE.
           STRING "POSTED RECORDS: " DELIMITED BY SIZE
                  WS-TOTAL-COUNT      DELIMITED BY SIZE
               INTO REPORT-LINE.
           WRITE REPORT-LINE.

           CLOSE POSTINGS-FILE.
           CLOSE REPORT-FILE.

           EXEC SQL COMMIT END-EXEC.
           EXEC SQL DISCONNECT ALL END-EXEC.
           STOP RUN.

       POST-ONE.
           MOVE PR-ACCOUNT-ID TO DB-ACCOUNT-ID.
           MOVE PR-AMOUNT     TO DB-AMOUNT.
           MOVE PR-CURRENCY   TO DB-CURRENCY.

           EXEC SQL
               INSERT INTO LEDGER.BALANCES
                   (ACCOUNT_ID, AMOUNT, CURRENCY, POSTED_AT)
               VALUES
                   (:DB-ACCOUNT-ID, :DB-AMOUNT, :DB-CURRENCY, NOW())
           END-EXEC.

           ADD 1 TO WS-TOTAL-COUNT.
