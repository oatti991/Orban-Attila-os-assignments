#include <stdio.h>
#include <pthread.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <semaphore.h>
#include <fcntl.h>
#include "a2_helper.h"

sem_t s1, s2;

typedef struct
{
    int process_no;
    int thread_no;

} TH_STRUCT;

void *t_func(void *arg)
{
    TH_STRUCT *s = (TH_STRUCT *)arg;
    int id = s->thread_no;

    if (id == 1)
    {
        sem_wait(&s1);
        info(BEGIN, s->process_no, id);
        info(END, s->process_no, id);
        sem_post(&s2);
    }
    else if (id == 3)
    {
        info(BEGIN, s->process_no, id);
        sem_post(&s1);
        sem_wait(&s2);
        info(END, s->process_no, id);
    }
    else
    {
        info(BEGIN, s->process_no, id);
        info(END, s->process_no, id);
        
    }
    pthread_exit(NULL);
}

void* t_func2(void *arg)
{
    
    TH_STRUCT *s = (TH_STRUCT *)arg;
    int id = s->thread_no;
    sem_wait(&s1);
    info(BEGIN, s->process_no, id);
    info(END, s->process_no, id);
    sem_post(&s1);
    pthread_exit(NULL);
}

void* t_func3(void *arg)
{
    TH_STRUCT *s = (TH_STRUCT *)arg;
    int id = s->thread_no;

    info(BEGIN, s->process_no, id);
    info(END, s->process_no, id);

    pthread_exit(NULL);

}

int main(int argc, char **argv)
{
    pthread_t arr[4];
    TH_STRUCT no[5];

    pthread_t arr2[40];
    TH_STRUCT no2[41];

    pthread_t arr3[6];
    TH_STRUCT no3[7];
    pid_t p2, p3, p4, p5, p6, p7, p8, p9;
    init();
    info(BEGIN, 1, 0);

    p2 = fork();
    if (p2 == 0)
    {
        info(BEGIN, 2, 0);
        
        

        p3 = fork();
        if (p3 == 0)
        {
            info(BEGIN, 3, 0);
            for (int i = 0; i < 6; i++)
                {
                    no3[i].process_no = 3;
                    no3[i].thread_no = i + 1;
                    pthread_create(&arr3[i], NULL, t_func3, &no3[i]);
                }
                for (int i = 0; i < 6; i++)
                {
                    pthread_join(arr3[i], NULL);
                }
            p4 = fork();
            if (p4 == 0)
            {
                info(BEGIN, 4, 0);

                sem_init(&s1, 0, 0);
                sem_init(&s2, 0, 0);

                for (int i = 0; i < 4; i++)
                {
                    no[i].process_no = 4;
                    no[i].thread_no = i + 1;
                    pthread_create(&arr[i], NULL, t_func, &no[i]);
                }
                for (int i = 0; i < 4; i++)
                {
                    pthread_join(arr[i], NULL);
                }
                info(END, 4, 0);
                exit(0);
            }
            p6 = fork();
            if (p6 == 0)
            {
                info(BEGIN, 6, 0);

                p9 = fork();
                if (p9 == 0)
                {
                    info(BEGIN, 9, 0);
                    info(END, 9, 0);
                    exit(0);
                }
                waitpid(p9, NULL, 0);
                info(END, 6, 0);
                exit(0);
            }
            waitpid(p4, NULL, 0);
            waitpid(p6, NULL, 0);
            info(END, 3, 0);
            exit(0);
        }

        p5 = fork();
        if (p5 == 0)
        {
            info(BEGIN, 5, 0);

            p8 = fork();
            if (p8 == 0)
            {
                info(BEGIN, 8, 0);
                info(END, 8, 0);
                exit(0);
            }
            waitpid(p8, NULL, 0);
            info(END, 5, 0);
            exit(0);
        }
        waitpid(p3, NULL, 0);
        waitpid(p5, NULL, 0);

        sem_init(&s1, 0, 6);
        for (int i = 0; i < 40; i++)
        {
            no2[i].process_no = 2;
            no2[i].thread_no = i + 1;
            pthread_create(&arr2[i], NULL, t_func2, &no2[i]);
        }
        for (int i = 0; i < 40; i++)
        {
            pthread_join(arr2[i], NULL);
        }
        sem_destroy(&s1);
        info(END, 2, 0);
        exit(0);
    }

    p7 = fork();
    if (p7 == 0)
    {
        info(BEGIN, 7, 0);
        info(END, 7, 0);
        exit(0);
    }

    waitpid(p2, NULL, 0);
    waitpid(p7, NULL, 0);
    info(END, 1, 0);
    exit(0);
    return 0;
}