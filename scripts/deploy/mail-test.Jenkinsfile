// Use in a separate temporary Pipeline job, without production deployment stages.
pipeline {
    agent any
    options {
        skipDefaultCheckout(true)
        timeout(time: 3, unit: 'MINUTES')
    }
    stages {
        stage('Test SMTP delivery') {
            steps {
                emailext(
                    to: '$DEFAULT_RECIPIENTS',
                    subject: '$DEFAULT_SUBJECT',
                    body: '$DEFAULT_CONTENT',
                    attachLog: false
                )
            }
        }
    }
}
