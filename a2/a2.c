#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <pthread.h>
#include "a2_helper.h"

typedef struct
{
    int process_no;
    int thread_no;
} TH_STRUCT;

void *thread_function(void *param)
{
    TH_STRUCT *s = (TH_STRUCT*)param;
    info(BEGIN,s->process_no,s->thread_no);

    if (s->process_no == 4 && s->thread_no == 1)
    {
        // Thread T4.1
        pthread_t t4_2, t4_3, t4_4;

        // Create threads T4.2, T4.3, T4.4
        TH_STRUCT s4_2 = { 4, 2 };
        TH_STRUCT s4_3 = { 4, 3 };
        TH_STRUCT s4_4 = { 4, 4 };
        pthread_create(&t4_2, NULL, thread_function, &s4_2);
        pthread_create(&t4_3, NULL, thread_function, &s4_3);
        pthread_create(&t4_4, NULL, thread_function, &s4_4);

        // Wait for threads T4.2, T4.3, T4.4 to complete
        pthread_join(t4_2, NULL);
        pthread_join(t4_3, NULL);
        pthread_join(t4_4, NULL);
    }

    info(END,s->process_no,s->thread_no);
    return NULL;
}


int main(int argc, char **argv)
{
    init();
    info(BEGIN,1,0);

    pid_t p2 = fork();
    if(p2 == 0)
    {
        info(BEGIN,2,0);

        pid_t p3 = fork();
        if(p3 == 0)
        {
            info(BEGIN,3,0);

            pid_t p4 = fork();
            if(p4 == 0)
            {
                info(BEGIN,4,0);

                // Create thread T4.1
                pthread_t t4_1;
                TH_STRUCT s4_1 = { 4, 1 };
                pthread_create(&t4_1, NULL, thread_function, &s4_1);

                // Wait for thread T4.1 to complete
                pthread_join(t4_1, NULL);

                info(END,4,0);
                exit(4);
            }

            pid_t p6 = fork();
            if(p6 == 0)
            {
                info(BEGIN,6,0);

                // Wait for thread T4.3 to start
                usleep(1000000);

                pid_t p9 = fork();
                if(p9 == 0)
                {
                    info(BEGIN,9,0);
                    info(END,9,0);
                    exit(9);
                }

                int s9 =0;
                waitpid(p9,&s9,0);
                info(END,6,0);
                exit(6);
            }

            int s4 = 0;
            int s6 = 0;
            waitpid(p4,&s4,0);
            waitpid(p6,&s6,0);
            info(END,3,0);
            exit(3);
        }

        pid_t p5 = fork();
        if(p5 == 0)
        {
            info(BEGIN,5,0);

            pid_t p8 = fork();
            if(p8 == 0)
            {
                info(BEGIN,8,0);
                info(END,8,0);
                exit(8);
            }
            int s8 =0;
            waitpid(p8,&s8,0);
            info(END,5,0);
            exit(5);
        }

        int s3 = 0;
        int s5 = 0;
        waitpid(p3, &s3, 0);
        waitpid(p5, &s5, 0);
        info(END,2,0);
        exit(2);
    }

    pid_t p7 = fork();
    if(p7 == 0)
    {
        info(BEGIN,7,0);
        info(END,7,0);
        exit(7);
    }

    int s2 = 0;
    int s7 = 0;
    waitpid(p2, &s2, 0);
    waitpid(p7, &s7, 0);
    info(END,1,0);
    exit(1);

    return 0;

}
