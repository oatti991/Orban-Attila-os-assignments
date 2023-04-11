#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h> 
#include <sys/socket.h>
#include <netinet/in.h>
#include <semaphore.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <pthread.h>
#include <sys/prctl.h>
#include <signal.h>

#include "a2_helper.h"

#define SEM_NAME "A2_HELPER_SEM_17871"
#define SERVER_PORT 1988

#define XSTR(s) STR(s)
#define STR(s) #s
#define CHECK(c) if(!(c)){perror("info function failed at line " XSTR(__LINE__)); break;}

int initialized = 0;

int info(int action, int processNr, int threadNr){
    int msg[6];
    int sleepTime = 0;
    int sockfd = -1;
    struct sockaddr_in serv_addr;
    sem_t *sem = SEM_FAILED;
    int err = -1;

    if(initialized == 0){
        printf("init() function not called\n");
        return -1;
    }
    do{
        CHECK((sem = sem_open(SEM_NAME, 0)) != SEM_FAILED);

        //prepare the message
        msg[0] = action;
        msg[1] = processNr;
        msg[2] = threadNr;
        msg[3] = getpid();
        msg[4] = getppid();
        msg[5] = (int)(long)pthread_self();

        CHECK((sockfd = socket(AF_INET, SOCK_STREAM, 0)) >= 0);
        
        memset(&serv_addr, 0, sizeof(serv_addr));
        serv_addr.sin_family = AF_INET;
        serv_addr.sin_port = htons(SERVER_PORT);

        CHECK(sem_wait(sem) == 0);
        err = -2;
        if(connect(sockfd, (struct sockaddr*)&serv_addr, sizeof(serv_addr)) >= 0){
            CHECK(write(sockfd, msg, sizeof(msg)) == sizeof(msg));
            CHECK(read(sockfd, &sleepTime, sizeof(sleepTime)) == sizeof(sleepTime));
            printf("[T] ");
        }else{
            printf("[ ] ");
        }
        printf("%s P%d T%d pid=%d ppid=%d tid=%d\n", msg[0]==BEGIN?"BEGIN":" END ", msg[1], msg[2], msg[3], msg[4], msg[5]);
        CHECK(sem_post(sem) == 0);
        err = -1;
        usleep(sleepTime);
        err = 0;
    }while(0);
    if(sockfd >= 0){
        close(sockfd);
    }
    if(err==-2){
        sem_post(sem);
    }
    return err;
}

void atfork_prepare(){
    sem_t *sem = SEM_FAILED;
    do{
        CHECK((sem = sem_open(SEM_NAME, O_CREAT, 0644, 1)) != SEM_FAILED);
        CHECK(sem_wait(sem) == 0);
    }while(0);
}

void atfork_parent(){
    sem_t *sem = SEM_FAILED;
    do{
        CHECK((sem = sem_open(SEM_NAME, O_CREAT, 0644, 1)) != SEM_FAILED);
        CHECK(sem_post(sem) == 0);
    }while(0);
}

void atfork_child(){
    prctl(PR_SET_PDEATHSIG, SIGHUP);
}

void init(){
    sem_t *sem = SEM_FAILED;
    if(initialized != 0){
        printf("init() function already called\n");
        return;
    }
    do{
        pthread_atfork(atfork_prepare, atfork_parent, atfork_child);
        sem_unlink(SEM_NAME);
        CHECK((sem = sem_open(SEM_NAME, O_CREAT, 0644, 1)) != SEM_FAILED);
        initialized = 1;
    }while(0);
}
