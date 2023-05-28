#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/mman.h>

#define REQ_PIPE_NAME "REQ_PIPE_81247"
#define RESP_PIPE_NAME "RESP_PIPE_81247"
#define SHM_NAME "/DMxPNN5a"
#define BUFFER_SIZE 128

const unsigned int VARIANT = 81247;
const unsigned int SHM_SIZE = 2512100;

int main() {
    if (mkfifo(RESP_PIPE_NAME, 0666) == -1)
    {
        perror("ERROR\ncannot create the response pipe");
        exit(1);
    }

    int req_fd = open(REQ_PIPE_NAME, O_RDONLY);
    if (req_fd == -1)
    {
        perror("ERROR\ncannot open the request pipe");
        exit(1);
    }

    int resp_fd = open(RESP_PIPE_NAME, O_WRONLY);
    if (resp_fd == -1)
    {
        perror("ERROR\ncannot open the response pipe");
        exit(1);
    }

    write(resp_fd, "HELLO#", strlen("HELLO#"));

    while (1)
    {
        char buffer[BUFFER_SIZE];
        read(req_fd, buffer, BUFFER_SIZE);
        char* command = strtok(buffer, "#");

        if (strcmp(command, "PING") == 0)
        {
            write(resp_fd, "PING#", strlen("PING#"));
            write(resp_fd, &VARIANT, sizeof(VARIANT));
            write(resp_fd, "PONG#", strlen("PONG#"));
        } 
        else if (strcmp(command, "CREATE_SHM") == 0)
        {
            int shm_fd = shm_open(SHM_NAME, O_RDWR | O_CREAT, 0664);
            if (shm_fd == -1)
            {
                perror("ERROR\ncannot open the shared memory");
                exit(1);
            }

            if (ftruncate(shm_fd, SHM_SIZE) == -1)
            {
                write(resp_fd, "CREATE_SHM#ERROR#", strlen("CREATE_SHM#ERROR#"));
            } else
            {
                write(resp_fd, "CREATE_SHM#SUCCESS#", strlen("CREATE_SHM#SUCCESS#"));
            }
            close(shm_fd);
        } 
        else
        {
            break;
        }
    }
    
    close(req_fd);
    close(resp_fd);
    unlink(RESP_PIPE_NAME);
    return 0;
}
